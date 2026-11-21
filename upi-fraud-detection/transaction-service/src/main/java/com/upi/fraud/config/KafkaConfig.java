package com.upi.fraud.config;

import org.apache.kafka.clients.admin.NewTopic;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.kafka.config.TopicBuilder;

@Configuration
public class KafkaConfig {

    @Value("${app.kafka.topics.raw-transactions:upi.transactions.raw}")
    private String rawTransactionsTopic;

    @Value("${app.kafka.topics.scored-transactions:upi.transactions.scored}")
    private String scoredTransactionsTopic;

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
}
