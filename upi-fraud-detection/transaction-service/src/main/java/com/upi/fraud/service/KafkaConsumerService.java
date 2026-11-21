package com.upi.fraud.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.upi.fraud.dto.ScoredTransactionEvent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Service;

@Service
public class KafkaConsumerService {

    private static final Logger log = LoggerFactory.getLogger(KafkaConsumerService.class);

    private final TransactionService transactionService;
    private final ObjectMapper objectMapper;

    public KafkaConsumerService(TransactionService transactionService, ObjectMapper objectMapper) {
        this.transactionService = transactionService;
        this.objectMapper = objectMapper;
    }

    @KafkaListener(topics = "${app.kafka.topics.scored-transactions:upi.transactions.scored}",
                   groupId = "${spring.kafka.consumer.group-id:upi-transaction-group}")
    public void consumeScoredTransaction(String message) {
        try {
            log.info("Received scored transaction message: {}", message);
            ScoredTransactionEvent event = objectMapper.readValue(message, ScoredTransactionEvent.class);
            if (event.getTransactionId() != null) {
                transactionService.updateScoredTransaction(
                        event.getTransactionId(),
                        event.getStatus() != null ? event.getStatus() : "APPROVED",
                        event.getRiskScore() != null ? event.getRiskScore() : 0,
                        event.getFlagReason()
                );
            } else {
                log.warn("Scored event missing transactionId: {}", message);
            }
        } catch (Exception e) {
            log.error("Failed to process scored transaction message: {}", message, e);
        }
    }
}
