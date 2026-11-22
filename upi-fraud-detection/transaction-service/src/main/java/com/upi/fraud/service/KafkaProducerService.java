package com.upi.fraud.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Service;

import java.util.Map;
import java.util.concurrent.TimeUnit;

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
        if (transactionPayload == null) {
            throw new IllegalArgumentException("transactionPayload cannot be null");
        }
        Object senderUpiObj = transactionPayload.get("senderUpi");
        if (senderUpiObj == null || String.valueOf(senderUpiObj).trim().isEmpty()) {
            throw new IllegalArgumentException("senderUpi is required for Kafka partition key");
        }
        String key = String.valueOf(senderUpiObj).trim();
        try {
            String value = objectMapper.writeValueAsString(transactionPayload);
            kafkaTemplate.send(rawTopic, key, value).whenComplete((result, ex) -> {
                if (ex == null) {
                    log.info("Published transaction {} to topic {} at offset {}",
                            transactionPayload.get("transactionId"), rawTopic, result.getRecordMetadata().offset());
                } else {
                    log.error("Failed async publishing transaction {} to topic {}: {}",
                            transactionPayload.get("transactionId"), rawTopic, ex.getMessage());
                }
            });
        } catch (JsonProcessingException e) {
            log.error("Error serializing transaction payload for transactionId {}: {}",
                    transactionPayload.get("transactionId"), e.getMessage());
            throw new RuntimeException("Serialization failure for Kafka message", e);
        }
    }
}
