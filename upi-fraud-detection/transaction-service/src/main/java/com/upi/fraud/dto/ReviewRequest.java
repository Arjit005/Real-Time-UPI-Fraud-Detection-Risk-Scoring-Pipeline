package com.upi.fraud.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;

public class ReviewRequest {

    @NotBlank(message = "status is required")
    @Pattern(regexp = "APPROVED|BLOCKED", message = "status must be either APPROVED or BLOCKED")
    private String status;

    private String reviewNotes;

    public ReviewRequest() {}

    public ReviewRequest(String status, String reviewNotes) {
        this.status = status;
        this.reviewNotes = reviewNotes;
    }

    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }

    public String getReviewNotes() { return reviewNotes; }
    public void setReviewNotes(String reviewNotes) { this.reviewNotes = reviewNotes; }
}
