package com.upi.fraud.config;

import org.apache.kafka.clients.admin.NewTopic;
import org.apache.kafka.common.TopicPartition;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.kafka.config.TopicBuilder;
import org.springframework.kafka.core.KafkaOperations;
import org.springframework.kafka.listener.DeadLetterPublishingRecoverer;
import org.springframework.kafka.listener.DefaultErrorHandler;
import org.springframework.util.backoff.FixedBackOff;

@Configuration
public class KafkaConfig {

    @Value("${app.kafka.topics.raw-transactions:upi.transactions.raw}")
    private String rawTransactionsTopic;

    @Value("${app.kafka.topics.scored-transactions:upi.transactions.scored}")
    private String scoredTransactionsTopic;

    @Value("${app.kafka.topics.dlq-transactions:upi.transactions.dlq}")
    private String dlqTopic;

    @Bean
    public NewTopic rawTransactionsTopic() {
        return TopicBuilder.name(rawTransactionsTopic)
                .partitions(3)
                .replicas(1)
                .build();
    }

    @Bean
    public NewTopic scoredTransactionsTopic() {
        return TopicBuilder.name(scoredTransactionsTopic)
                .partitions(3)
                .replicas(1)
                .build();
    }

    @Bean
    public NewTopic dlqTransactionsTopic() {
        return TopicBuilder.name(dlqTopic)
                .partitions(3)
                .replicas(1)
                .build();
    }

    @Bean
    public DefaultErrorHandler defaultErrorHandler(KafkaOperations<Object, Object> operations) {
        DeadLetterPublishingRecoverer recoverer = new DeadLetterPublishingRecoverer(operations,
                (record, ex) -> new TopicPartition(dlqTopic, -1));
        return new DefaultErrorHandler(recoverer, new FixedBackOff(1000L, 2L));
    }
}
