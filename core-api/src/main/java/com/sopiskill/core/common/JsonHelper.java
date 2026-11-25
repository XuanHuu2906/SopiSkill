package com.sopiskill.core.common;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Component;

@Component
public class JsonHelper {

    private final ObjectMapper objectMapper;

    public JsonHelper(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    public String toJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException ex) {
            throw new IllegalStateException("Failed to serialize JSON", ex);
        }
    }

    public <T> T fromJson(String raw, TypeReference<T> typeRef) {
        try {
            return objectMapper.readValue(raw, typeRef);
        } catch (JsonProcessingException ex) {
            throw new IllegalStateException("Failed to deserialize JSON", ex);
        }
    }

    public <T> T fromJson(String raw, Class<T> clazz) {
        try {
            return objectMapper.readValue(raw, clazz);
        } catch (JsonProcessingException ex) {
            throw new IllegalStateException("Failed to deserialize JSON", ex);
        }
    }
}
