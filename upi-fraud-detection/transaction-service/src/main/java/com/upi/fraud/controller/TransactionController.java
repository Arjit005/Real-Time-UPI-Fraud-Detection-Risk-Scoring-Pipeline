package com.upi.fraud.controller;

import com.upi.fraud.dto.ReviewRequest;
import com.upi.fraud.dto.TransactionRequest;
import com.upi.fraud.dto.TransactionResponse;
import com.upi.fraud.service.TransactionService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api/v1/transactions")
public class TransactionController {

    private final TransactionService transactionService;

    public TransactionController(TransactionService transactionService) {
        this.transactionService = transactionService;
    }

    @PostMapping
    public ResponseEntity<TransactionResponse> createTransaction(
            @Valid @RequestBody TransactionRequest request,
            @RequestHeader(value = "Idempotency-Key", required = false) String idempotencyKey) {
        TransactionResponse response = transactionService.processTransaction(request, idempotencyKey);
        return ResponseEntity.status(HttpStatus.CREATED).body(response);
    }

    @GetMapping
    public ResponseEntity<List<TransactionResponse>> getRecentTransactions(
            @RequestParam(value = "limit", defaultValue = "50") int limit,
            @RequestParam(value = "status", required = false) String status) {
        List<TransactionResponse> list = transactionService.getRecentTransactions(limit, status);
        return ResponseEntity.ok(list);
    }

    @PatchMapping("/{id}/review")
    public ResponseEntity<TransactionResponse> reviewTransaction(
            @PathVariable("id") UUID transactionId,
            @Valid @RequestBody ReviewRequest reviewRequest) {
        TransactionResponse response = transactionService.reviewTransaction(transactionId, reviewRequest);
        return ResponseEntity.ok(response);
    }
}
