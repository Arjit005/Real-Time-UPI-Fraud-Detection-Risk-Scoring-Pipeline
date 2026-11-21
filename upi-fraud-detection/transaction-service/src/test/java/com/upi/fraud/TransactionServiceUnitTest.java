package com.upi.fraud;

import com.upi.fraud.dto.TransactionRequest;
import com.upi.fraud.dto.TransactionResponse;
import com.upi.fraud.entity.TransactionEntity;
import com.upi.fraud.entity.TransactionStatus;
import com.upi.fraud.repository.TransactionRepository;
import com.upi.fraud.service.IdempotencyService;
import com.upi.fraud.service.KafkaProducerService;
import com.upi.fraud.service.TransactionService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
public class TransactionServiceUnitTest {

    @Mock
    private TransactionRepository transactionRepository;

    @Mock
    private KafkaProducerService kafkaProducerService;

    @Mock
    private IdempotencyService idempotencyService;

    @InjectMocks
    private TransactionService transactionService;

    private TransactionRequest sampleRequest;
    private TransactionEntity savedEntity;

    @BeforeEach
    void setUp() {
        sampleRequest = new TransactionRequest(
                "arjit@okhdfc",
                "swiggy@icici",
                new BigDecimal("450.00"),
                "Bengaluru",
                "pixel_9"
        );

        savedEntity = new TransactionEntity();
        savedEntity.setTransactionId(UUID.randomUUID());
        savedEntity.setSenderUpi(sampleRequest.getSenderUpi());
        savedEntity.setReceiverUpi(sampleRequest.getReceiverUpi());
        savedEntity.setAmount(sampleRequest.getAmount());
        savedEntity.setCity(sampleRequest.getCity());
        savedEntity.setDeviceId(sampleRequest.getDeviceId());
        savedEntity.setStatus(TransactionStatus.PENDING);
        savedEntity.setRiskScore(0);
        savedEntity.setCreatedAt(Instant.now());
    }

    @Test
    @DisplayName("Unit Test: New transaction is saved as PENDING, published to Kafka, and cached")
    void testProcessTransactionSuccess() {
        when(idempotencyService.getCachedResponse("idem-123")).thenReturn(null);
        when(transactionRepository.save(any(TransactionEntity.class))).thenReturn(savedEntity);

        TransactionResponse response = transactionService.processTransaction(sampleRequest, "idem-123");

        assertNotNull(response);
        assertEquals(TransactionStatus.PENDING, response.getStatus());
        assertEquals(new BigDecimal("450.00"), response.getAmount());

        verify(kafkaProducerService, times(1)).publishRawTransaction(any());
        verify(idempotencyService, times(1)).cacheResponse(eq("idem-123"), any(TransactionResponse.class));
    }

    @Test
    @DisplayName("Unit Test: Idempotency Key hit returns cached response with ZERO duplicate DB insert")
    void testIdempotencyKeyBlocksDuplicate() {
        TransactionResponse cached = TransactionResponse.fromEntity(savedEntity);
        when(idempotencyService.getCachedResponse("idem-duplicate")).thenReturn(cached);

        TransactionResponse result = transactionService.processTransaction(sampleRequest, "idem-duplicate");

        assertSame(cached, result);
        verify(transactionRepository, never()).save(any());
        verify(kafkaProducerService, never()).publishRawTransaction(any());
    }

    @Test
    @DisplayName("Unit Test: Scored event updates transaction status, risk score, and flag reason")
    void testUpdateScoredTransaction() {
        UUID txnId = savedEntity.getTransactionId();
        when(transactionRepository.findById(txnId)).thenReturn(java.util.Optional.of(savedEntity));

        transactionService.updateScoredTransaction(txnId, "FLAGGED", 85, "High velocity | Impossible travel");

        assertEquals(TransactionStatus.FLAGGED, savedEntity.getStatus());
        assertEquals(85, savedEntity.getRiskScore());
        assertEquals("High velocity | Impossible travel", savedEntity.getFlagReason());
        verify(transactionRepository, times(1)).save(savedEntity);
    }
}
