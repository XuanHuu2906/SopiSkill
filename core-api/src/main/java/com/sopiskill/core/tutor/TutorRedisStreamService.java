package com.sopiskill.core.tutor;

import jakarta.annotation.PreDestroy;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.Range;
import org.springframework.data.redis.connection.MessageListener;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.connection.stream.MapRecord;
import org.springframework.data.redis.connection.stream.RecordId;
import org.springframework.data.redis.connection.stream.StreamRecords;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.listener.ChannelTopic;
import org.springframework.data.redis.listener.RedisMessageListenerContainer;
import org.springframework.stereotype.Service;

/**
 * Multi-pod Tutor SSE coordination backed by Redis 7:
 *  - `tutor:stream:{messageId}` (Redis Stream, TTL 10 min): sequential SSE frame buffer so ANY pod
 *    can replay missed frames on `Last-Event-ID` reconnect.
 *  - `tutor:cancel:{messageId}` (Redis Pub/Sub) + `tutor:cancelled:{messageId}` flag (TTL 10 min):
 *    instant cross-pod stream cancellation when `/stop` lands on a different replica.
 */
@Service
public class TutorRedisStreamService {

    private static final Logger log = LoggerFactory.getLogger(TutorRedisStreamService.class);
    private static final Duration STREAM_TTL = Duration.ofMinutes(10);

    public record BufferedFrame(String id, String event, String data) {}

    private final StringRedisTemplate redis;
    private final RedisMessageListenerContainer pubSubContainer;

    public TutorRedisStreamService(StringRedisTemplate redis, RedisConnectionFactory connectionFactory) {
        this.redis = redis;
        this.pubSubContainer = new RedisMessageListenerContainer();
        this.pubSubContainer.setConnectionFactory(connectionFactory);
        this.pubSubContainer.afterPropertiesSet();
        this.pubSubContainer.start();
    }

    @PreDestroy
    public void shutdown() {
        try {
            pubSubContainer.stop();
            pubSubContainer.destroy();
        } catch (Exception ex) {
            log.debug("tutor_pubsub_shutdown_ignored type={}", ex.getClass().getSimpleName());
        }
    }

    public static String streamKey(String formattedMsgId) {
        return "tutor:stream:" + formattedMsgId;
    }

    public static String cancelChannel(String formattedMsgId) {
        return "tutor:cancel:" + formattedMsgId;
    }

    public static String cancelFlagKey(String formattedMsgId) {
        return "tutor:cancelled:" + formattedMsgId;
    }

    public String appendFrame(String formattedMsgId, String eventName, String jsonData) {
        String key = streamKey(formattedMsgId);
        try {
            RecordId id = redis.opsForStream().add(
                    StreamRecords.string(Map.of("event", eventName, "data", jsonData)).withStreamKey(key)
            );
            redis.expire(key, STREAM_TTL);
            return id != null ? id.getValue() : String.valueOf(System.currentTimeMillis()) + "-0";
        } catch (Exception ex) {
            log.warn("tutor_stream_append_failed msg={} type={}", formattedMsgId, ex.getClass().getSimpleName());
            return String.valueOf(System.currentTimeMillis()) + "-0";
        }
    }

    public boolean streamExists(String formattedMsgId) {
        try {
            return Boolean.TRUE.equals(redis.hasKey(streamKey(formattedMsgId)));
        } catch (Exception ex) {
            return false;
        }
    }

    public List<BufferedFrame> readFramesAfter(String formattedMsgId, String lastEventId) {
        String key = streamKey(formattedMsgId);
        Range<String> range;
        if (lastEventId == null || lastEventId.isBlank() || "0".equals(lastEventId) || "0-0".equals(lastEventId)) {
            range = Range.unbounded();
        } else {
            range = Range.rightUnbounded(Range.Bound.exclusive(lastEventId.trim()));
        }
        try {
            List<MapRecord<String, Object, Object>> records = redis.opsForStream().range(key, range);
            if (records == null || records.isEmpty()) return List.of();
            List<BufferedFrame> out = new ArrayList<>(records.size());
            for (MapRecord<String, Object, Object> rec : records) {
                Map<Object, Object> val = rec.getValue();
                String ev = val.get("event") == null ? "message" : String.valueOf(val.get("event"));
                String data = val.get("data") == null ? "{}" : String.valueOf(val.get("data"));
                out.add(new BufferedFrame(rec.getId().getValue(), ev, data));
            }
            return out;
        } catch (Exception ex) {
            log.warn("tutor_stream_range_failed msg={} type={}", formattedMsgId, ex.getClass().getSimpleName());
            return List.of();
        }
    }

    public void publishCancel(String formattedMsgId) {
        try {
            redis.opsForValue().set(cancelFlagKey(formattedMsgId), "1", STREAM_TTL);
            redis.convertAndSend(cancelChannel(formattedMsgId), "stop");
        } catch (Exception ex) {
            log.warn("tutor_cancel_publish_failed msg={} type={}", formattedMsgId, ex.getClass().getSimpleName());
        }
    }

    public boolean isCancelledFlagged(String formattedMsgId) {
        try {
            return Boolean.TRUE.equals(redis.hasKey(cancelFlagKey(formattedMsgId)));
        } catch (Exception ex) {
            return false;
        }
    }

    /**
     * Subscribes to `tutor:cancel:{msgId}` on Redis Pub/Sub and returns an unsubscribe callback.
     */
    public Runnable subscribeCancel(String formattedMsgId, Runnable onCancel) {
        ChannelTopic topic = new ChannelTopic(cancelChannel(formattedMsgId));
        MessageListener listener = (message, pattern) -> onCancel.run();
        pubSubContainer.addMessageListener(listener, topic);
        if (isCancelledFlagged(formattedMsgId)) {
            onCancel.run();
        }
        return () -> pubSubContainer.removeMessageListener(listener, topic);
    }
}
