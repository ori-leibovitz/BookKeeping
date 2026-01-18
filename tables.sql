-- Generated from: https://drawsql.app/teams/get-shit-done/diagrams/oribookkeeping
-- How to connect: PGPASSWORD='example' psql -U postgres -h localhost -d mydatabase

CREATE TABLE IF NOT EXISTS "users" (
    "id" UUID NOT NULL,
    "first_name" TEXT NOT NULL,
    "last_name" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "password" TEXT NOT NULL,
    "created_at" TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    "updated_at" TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL
);

CREATE TABLE IF NOT EXISTS "accounts" (
    "id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "account_number" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "balance_cents" BIGINT NOT NULL,
    "created_at" TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    "updated_at" TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL
);

CREATE TABLE IF NOT EXISTS "transactions" (
    "id" UUID NOT NULL,
    "initiator_id" UUID NOT NULL,
    "from_bank_account_id" UUID,
    "to_bank_account_id" UUID,
    "amount" BIGINT NOT NULL,
    "created_at" TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    "updated_at" TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL
);

-- ===== טבלה חדשה למשימה 2! =====
-- טבלה זו תאחסן את בקשות ההעברה עם states
CREATE TABLE IF NOT EXISTS "transfer_requests" (
    "id" UUID NOT NULL,
    "initiator_id" UUID NOT NULL,
    "from_account_id" UUID NOT NULL,
    "to_account_id" UUID NOT NULL,
    "amount" BIGINT NOT NULL,
    "state" TEXT NOT NULL, -- pending, approved, declined, completed, failed
    "requires_approval" BOOLEAN NOT NULL DEFAULT false,
    "approved_by" UUID,
    "decline_reason" TEXT,
    "transaction_id" UUID,
    "created_at" TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    "updated_at" TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL
);

-- Indexes for users
CREATE INDEX IF NOT EXISTS "users_email_index" ON "users"("email");
ALTER TABLE "users" ADD PRIMARY KEY("id");
ALTER TABLE "users" ADD CONSTRAINT "users_email_unique" UNIQUE("email");

-- Indexes for accounts
CREATE INDEX IF NOT EXISTS "accounts_account_number_index" ON "accounts"("account_number");
ALTER TABLE "accounts" ADD PRIMARY KEY("id");
ALTER TABLE "accounts" ADD CONSTRAINT "accounts_owner_id_foreign" FOREIGN KEY("owner_id") REFERENCES "users"("id");

-- Constraints for transactions
ALTER TABLE "transactions" ADD PRIMARY KEY("id");
ALTER TABLE "transactions" ADD CONSTRAINT "transactions_from_bank_account_id_foreign" FOREIGN KEY("from_bank_account_id") REFERENCES "accounts"("id");
ALTER TABLE "transactions" ADD CONSTRAINT "transactions_to_bank_account_id_foreign" FOREIGN KEY("to_bank_account_id") REFERENCES "accounts"("id");

-- ===== Indexes ו-Constraints עבור transfer_requests =====
CREATE INDEX IF NOT EXISTS "transfer_requests_state_index" ON "transfer_requests"("state");
CREATE INDEX IF NOT EXISTS "transfer_requests_initiator_id_index" ON "transfer_requests"("initiator_id");
ALTER TABLE "transfer_requests" ADD PRIMARY KEY("id");
ALTER TABLE "transfer_requests" ADD CONSTRAINT "transfer_requests_initiator_id_foreign" FOREIGN KEY("initiator_id") REFERENCES "users"("id");
ALTER TABLE "transfer_requests" ADD CONSTRAINT "transfer_requests_from_account_id_foreign" FOREIGN KEY("from_account_id") REFERENCES "accounts"("id");
ALTER TABLE "transfer_requests" ADD CONSTRAINT "transfer_requests_to_account_id_foreign" FOREIGN KEY("to_account_id") REFERENCES "accounts"("id");
ALTER TABLE "transfer_requests" ADD CONSTRAINT "transfer_requests_transaction_id_foreign" FOREIGN KEY("transaction_id") REFERENCES "transactions"("id");

-- ✅ OTP Support: Add registration_status column
ALTER TABLE users ADD COLUMN IF NOT EXISTS registration_status VARCHAR(20) DEFAULT 'pending';

-- User Roles & Permissions
ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'user';

-- Valid roles: 'admin', 'user', 'viewer'
-- Add check constraint
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'users_role_check'
    ) THEN
        ALTER TABLE users ADD CONSTRAINT users_role_check 
        CHECK (role IN ('admin', 'user', 'viewer'));
    END IF;
END $$;