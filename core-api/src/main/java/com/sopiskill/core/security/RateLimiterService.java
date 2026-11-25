package com.sopiskill.core.security;

import com.sopiskill.core.common.ApiException;
import com.sopiskill.core.config.SopiProperties;
import jakarta.servlet.http.HttpServletRequest;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

/**
 * Distributed sliding-window rate limiter using atomic Redis Lua script (`ZREMRANGEBYSCORE` + `ZCARD` + `ZADD` + `PEXPIRE`),
 * with in-memory fallback or fail-closed mode when Redis is unavailable.
 */
@Service
public class RateLimiterService {

    private static final Logger log = LoggerFactory.getLogger(RateLimiterService.class);

    private static final DefaultRedisScript<Long> SLIDING_WINDOW_SCRIPT = new DefaultRedisScript<>(
            """
            local key = KEYS[1]
            local now = tonumber(ARGV[1])
            local window_ms = tonumber(ARGV[2])
            local limit = tonumber(ARGV[3])
            local member = ARGV[4]
            redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window_ms)
            local count = redis.call('ZCARD', key)
            if count >= limit then
                local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
                local retry_ms = window_ms
                if oldest[2] then
                    retry_ms = math.max(1000, window_ms - (now - tonumber(oldest[2])))
                end
                return -retry_ms
            end
            redis.call('ZADD', key, now, member)
            redis.call('PEXPIRE', key, window_ms + 1000)
            return count + 1
            """,
            Long.class
    );

    private final StringRedisTemplate redis;
    private final SopiProperties props;
    private final ConcurrentHashMap<String, Deque<Long>> memoryBuckets = new ConcurrentHashMap<>();

    public RateLimiterService(StringRedisTemplate redis, SopiProperties props) {
        this.redis = redis;
        this.props = props;
    }

    public void check(HttpServletRequest request, String scope, int limit, int windowSeconds) {
        if (!props.rateLimitEnabled()) {
            return;
        }
        String clientIp = request.getRemoteAddr() == null ? "unknown" : request.getRemoteAddr();
        String key = "rl:" + scope + ":" + clientIp;
        long nowMs = System.currentTimeMillis();
        long windowMs = windowSeconds * 1000L;

        try {
            Long result = redis.execute(
                    SLIDING_WINDOW_SCRIPT,
                    List.of(key),
                    String.valueOf(nowMs),
                    String.valueOf(windowMs),
                    String.valueOf(limit),
                    nowMs + ":" + UUID.randomUUID()
            );
            if (result != null && result < 0) {
                long retrySeconds = Math.max(1L, (-result + 999L) / 1000L);
                throw new ApiException(
                        HttpStatus.TOO_MANY_REQUESTS,
                        "RATE_LIMITED",
                        "Bạn thao tác quá nhanh. Vui lòng thử lại sau.",
                        Map.of("retryAfterSeconds", retrySeconds)
                );
            }
            return;
        } catch (ApiException ex) {
            throw ex;
        } catch (Exception ex) {
            log.warn("rate_limiter_redis_unavailable scope={} errorType={}", scope, ex.getClass().getSimpleName());
            if (props.rateLimitFailClosed()) {
                throw new ApiException(
                        HttpStatus.SERVICE_UNAVAILABLE,
                        "RATE_LIMITER_UNAVAILABLE",
                        "Dịch vụ giới hạn tốc độ tạm thời gián đoạn."
                );
            }
        }

        // In-memory fallback for dev/unit tests when Redis is down
        Deque<Long> deque = memoryBuckets.computeIfAbsent(key, ignored -> new ArrayDeque<>());
        synchronized (deque) {
            while (!deque.isEmpty() && nowMs - deque.peekFirst() >= windowMs) {
                deque.pollFirst();
            }
            if (deque.size() >= limit) {
                long oldest = deque.peekFirst() == null ? nowMs : deque.peekFirst();
                long retrySeconds = Math.max(1L, (windowMs - (nowMs - oldest) + 999L) / 1000L);
                throw new ApiException(
                        HttpStatus.TOO_MANY_REQUESTS,
                        "RATE_LIMITED",
                        "Bạn thao tác quá nhanh. Vui lòng thử lại sau.",
                        Map.of("retryAfterSeconds", retrySeconds)
                );
            }
            deque.addLast(nowMs);
        }
    }
}
