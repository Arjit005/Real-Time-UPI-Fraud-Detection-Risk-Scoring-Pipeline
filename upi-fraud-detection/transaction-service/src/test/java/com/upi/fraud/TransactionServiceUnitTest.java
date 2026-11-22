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

        savedEntity = new TransactionEntity(
                UUID.randomUUID(),
                sampleRequest.getSenderUpi(),
                sampleRequest.getReceiverUpi(),
                sampleRequest.getAmount(),
                sampleRequest.getCity(),
                sampleRequest.getDeviceId(),
                TransactionStatus.PENDING,
                0,
                null,
                Instant.now()
        );
    }

    @Test
    @DisplayName("Unit Test: New transaction is saved as PENDING, published to Kafka, and cached")
    void testProcessTransactionSuccess() {
        when(idempotencyService.claimKey(eq("idem-123"), any()))
                .thenReturn(new IdempotencyService.ClaimResult(true, "token-123", null));
        when(idempotencyService.computePayloadHash(any())).thenReturn("samplehash");
        when(transactionRepository.save(any(TransactionEntity.class))).thenReturn(savedEntity);

        TransactionResponse response = transactionService.processTransaction(sampleRequest, "idem-123");

        assertNotNull(response);
        assertEquals(TransactionStatus.PENDING, response.getStatus());
        assertEquals(new BigDecimal("450.00"), response.getAmount());

        verify(kafkaProducerService, times(1)).publishRawTransaction(any());
        verify(idempotencyService, times(1)).cacheResponse(eq("idem-123"), any(TransactionResponse.class), eq("samplehash"), eq("token-123"));
    }

    @Test
    @DisplayName("Unit Test: Idempotency Key hit returns cached response with ZERO duplicate DB insert")
    void testIdempotencyKeyBlocksDuplicate() {
        TransactionResponse cached = TransactionResponse.fromEntity(savedEntity);
        when(idempotencyService.claimKey(eq("idem-duplicate"), any()))
                .thenReturn(new IdempotencyService.ClaimResult(false, null, cached));

        TransactionResponse result = transactionService.processTransaction(sampleRequest, "idem-duplicate");

        assertSame(cached, result);
        verify(transactionRepository, never()).save(any());
        verify(kafkaProducerService, never()).publishRawTransaction(any());
    }

    @Test
    @DisplayName("Unit Test: Idempotency Key in progress throws 409 Conflict")
    void testIdempotencyKeyInProgressThrowsConflict() {
        when(idempotencyService.claimKey(eq("idem-in-progress"), any()))
                .thenThrow(new org.springframework.web.server.ResponseStatusException(
                        org.springframework.http.HttpStatus.CONFLICT, "Transaction is currently in progress"));

        assertThrows(org.springframework.web.server.ResponseStatusException.class, () -> {
            transactionService.processTransaction(sampleRequest, "idem-in-progress");
        });

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
