package com.sopiskill.core.common;

import java.util.LinkedHashMap;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @ExceptionHandler(ApiException.class)
    public ResponseEntity<Map<String, Object>> handleApi(ApiException ex) {
        HttpHeaders headers = new HttpHeaders();
        Object retryAfter = ex.toDetailMap().get("retryAfterSeconds");
        if (retryAfter instanceof Number num) {
            headers.set("Retry-After", String.valueOf(num.longValue()));
        }
        return ResponseEntity.status(ex.getStatus())
                .headers(headers)
                .body(Map.of("detail", ex.toDetailMap()));
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<Map<String, Object>> handleValidation(MethodArgumentNotValidException ex) {
        String msg = ex.getBindingResult().getFieldErrors().stream()
                .findFirst()
                .map(fe -> fe.getField() + ": " + fe.getDefaultMessage())
                .orElse("Dữ liệu gửi lên không hợp lệ.");
        Map<String, Object> detail = new LinkedHashMap<>();
        detail.put("code", "VALIDATION_ERROR");
        detail.put("message", msg);
        return ResponseEntity.status(HttpStatus.UNPROCESSABLE_ENTITY)
                .body(Map.of("detail", detail));
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<Map<String, Object>> handleUnreadable(HttpMessageNotReadableException ex) {
        Map<String, Object> detail = new LinkedHashMap<>();
        detail.put("code", "INVALID_JSON");
        detail.put("message", "Payload JSON không hợp lệ.");
        return ResponseEntity.status(HttpStatus.UNPROCESSABLE_ENTITY)
                .body(Map.of("detail", detail));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, Object>> handleUnexpected(Exception ex) {
        log.error("unhandled_exception type={}", ex.getClass().getSimpleName(), ex);
        Map<String, Object> detail = new LinkedHashMap<>();
        detail.put("code", "INTERNAL_ERROR");
        detail.put("message", "Đã xảy ra lỗi hệ thống.");
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(Map.of("detail", detail));
    }
}
