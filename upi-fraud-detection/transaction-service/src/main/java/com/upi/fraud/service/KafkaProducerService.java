package com.upi.fraud.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Service;

import java.util.Map;

@Service
public class KafkaProducerService {

    private static final Logger log = LoggerFactory.getLogger(KafkaProducerService.class);

    private final KafkaTemplate<String, String> kafkaTemplate;
    private final ObjectMapper objectMapper;

    @Value("${app.kafka.topics.raw-transactions:upi.transactions.raw}")
    private String rawTopic;

    public KafkaProducerService(KafkaTemplate<String, String> kafkaTemplate, ObjectMapper objectMapper) {
        this.kafkaTemplate = kafkaTemplate;
        this.objectMapper = objectMapper;
    }

    public void publishRawTransaction(Map<String, Object> transactionPayload) {
        try {
            String key = String.valueOf(transactionPayload.get("senderUpi"));
            String value = objectMapper.writeValueAsString(transactionPayload);
            kafkaTemplate.send(rawTopic, key, value).whenComplete((result, ex) -> {
                if (ex != null) {
                    log.error("Failed to publish transaction {} to topic {}", key, rawTopic, ex);
                } else {
                    log.info("Published transaction {} to topic {} at offset {}",
                            transactionPayload.get("transactionId"), rawTopic, result.getRecordMetadata().offset());
                }
            });
        } catch (JsonProcessingException e) {
            log.error("Error serializing transaction payload: {}", transactionPayload, e);
            throw new RuntimeException("Serialization failure for Kafka message", e);
        }
    }
}
