package com.upi.fraud.dto;

import com.upi.fraud.entity.TransactionEntity;
import com.upi.fraud.entity.TransactionStatus;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

public class TransactionResponse {

    private UUID transactionId;
    private String senderUpi;
    private String receiverUpi;
    private BigDecimal amount;
    private String city;
    private String deviceId;
    private TransactionStatus status;
    private Integer riskScore;
    private String flagReason;
    private Instant createdAt;

    public TransactionResponse() {}

    public static TransactionResponse fromEntity(TransactionEntity entity) {
        TransactionResponse res = new TransactionResponse();
        res.setTransactionId(entity.getTransactionId());
        res.setSenderUpi(entity.getSenderUpi());
        res.setReceiverUpi(entity.getReceiverUpi());
        res.setAmount(entity.getAmount());
        res.setCity(entity.getCity());
        res.setDeviceId(entity.getDeviceId());
        res.setStatus(entity.getStatus());
        res.setRiskScore(entity.getRiskScore());
        res.setFlagReason(entity.getFlagReason());
        res.setCreatedAt(entity.getCreatedAt());
        return res;
    }

    public UUID getTransactionId() { return transactionId; }
    public void setTransactionId(UUID transactionId) { this.transactionId = transactionId; }

    public String getSenderUpi() { return senderUpi; }
    public void setSenderUpi(String senderUpi) { this.senderUpi = senderUpi; }

    public String getReceiverUpi() { return receiverUpi; }
    public void setReceiverUpi(String receiverUpi) { this.receiverUpi = receiverUpi; }

    public BigDecimal getAmount() { return amount; }
    public void setAmount(BigDecimal amount) { this.amount = amount; }

    public String getCity() { return city; }
    public void setCity(String city) { this.city = city; }

    public String getDeviceId() { return deviceId; }
    public void setDeviceId(String deviceId) { this.deviceId = deviceId; }

    public TransactionStatus getStatus() { return status; }
    public void setStatus(TransactionStatus status) { this.status = status; }

    public Integer getRiskScore() { return riskScore; }
    public void setRiskScore(Integer riskScore) { this.riskScore = riskScore; }

    public String getFlagReason() { return flagReason; }
    public void setFlagReason(String flagReason) { this.flagReason = flagReason; }

    public Instant getCreatedAt() { return createdAt; }
    public void setCreatedAt(Instant createdAt) { this.createdAt = createdAt; }
}
