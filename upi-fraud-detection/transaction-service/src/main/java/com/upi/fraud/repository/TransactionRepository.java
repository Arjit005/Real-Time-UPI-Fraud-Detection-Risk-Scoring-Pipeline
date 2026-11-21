package com.upi.fraud.repository;

import com.upi.fraud.entity.TransactionEntity;
import com.upi.fraud.entity.TransactionStatus;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.UUID;

@Repository
public interface TransactionRepository extends JpaRepository<TransactionEntity, UUID> {
    List<TransactionEntity> findAllByOrderByCreatedAtDesc(Pageable pageable);
    List<TransactionEntity> findByStatusOrderByCreatedAtDesc(TransactionStatus status, Pageable pageable);
}
