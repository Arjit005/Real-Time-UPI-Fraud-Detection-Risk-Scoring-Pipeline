package com.upi.fraud.dto;

import java.math.BigDecimal;
import java.util.UUID;

public class ScoredTransactionEvent {

    private UUID transactionId;
    private String senderUpi;
    private String receiverUpi;
    private BigDecimal amount;
    private String city;
    private String deviceId;
    private String status;
    private Integer riskScore;
    private String flagReason;

    public ScoredTransactionEvent() {}

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

    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }

    public Integer getRiskScore() { return riskScore; }
    public void setRiskScore(Integer riskScore) { this.riskScore = riskScore; }

    public String getFlagReason() { return flagReason; }
    public void setFlagReason(String flagReason) { this.flagReason = flagReason; }
}
