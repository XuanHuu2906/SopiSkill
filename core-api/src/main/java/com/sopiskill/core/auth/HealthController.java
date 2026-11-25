package com.sopiskill.core.auth;

import com.sopiskill.core.config.SopiProperties;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class HealthController {

    private final JdbcClient jdbc;
    private final StringRedisTemplate redis;
    private final SopiProperties props;

    public HealthController(JdbcClient jdbc, StringRedisTemplate redis, SopiProperties props) {
        this.jdbc = jdbc;
        this.redis = redis;
        this.props = props;
    }

    @GetMapping("/health")
    public Map<String, Object> health() {
        return Map.of(
                "status", "ok",
                "service", "sopiskill-core-api",
                "env", props.env()
        );
    }

    @GetMapping("/ready")
    public ResponseEntity<Map<String, Object>> ready() {
        Map<String, String> checks = new LinkedHashMap<>();
        boolean healthy = true;

        try {
            jdbc.sql("SELECT 1").query(Integer.class).single();
            checks.put("database", "ok");
        } catch (Exception ex) {
            checks.put("database", "error");
            healthy = false;
        }

        try {
            String pong = redis.getConnectionFactory() == null
                    ? null
                    : redis.getConnectionFactory().getConnection().ping();
            checks.put("redis", "PONG".equalsIgnoreCase(pong) ? "ok" : "error");
            if (!"ok".equals(checks.get("redis"))) healthy = false;
        } catch (Exception ex) {
            checks.put("redis", "error");
            healthy = false;
        }

        checks.put("config", "ok");

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("status", healthy ? "ready" : "not_ready");
        body.put("env", props.env());
        body.put("checks", checks);
        body.put("warnings", List.of());
        return ResponseEntity.status(healthy ? HttpStatus.OK : HttpStatus.SERVICE_UNAVAILABLE).body(body);
    }
}
