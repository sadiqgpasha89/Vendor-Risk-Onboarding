# Vendor Risk Onboarding: diagrams (Mermaid)

Paste each block into https://mermaid.live (or any Mermaid viewer) and export PNG or SVG for Medium.

## 1. Architecture (vro-agents)

```mermaid
flowchart TB
    USERS["Users<br/>sponsor · analyst · AML · senior risk · committee · head of TPRM"]
    HOOKS["Webhooks<br/>sanctions list updates · vendor portal"]

    subgraph API["API: Starlette, stateless replicas"]
        direction TB
        AUTH["Auth and limits<br/>OIDC JWT (RS256/ES256) · token-bucket rate limits · tenant scoping"]
        A0["A0 Workflow engine<br/>deterministic state machine · gates G0-G4, GX · segregation of duties"]
        POL[("Policy packs<br/>scoring.yaml · gates.yaml · EU / IN / US overlays<br/>version = content hash")]

        subgraph AG["Agents: propose only"]
            direction LR
            A1["A1 Intake<br/>entity resolution"]
            A2["A2 Screening<br/>recommend, never clear"]
            A3["A3 Tiering"]
            A4["A4 Reader<br/>NO tools"]
            SP["A5-A8 Specialists<br/>security · financial · regulatory · concentration"]
            A10["A10 Independent verifier"]
            A11["A11 Steward<br/>staleness sweeps"]
            A12["A12 Comms drafter<br/>drafts only"]
        end

        VAL["Validators<br/>schema · quote located · value supported · language safety"]
        LED[("Claim ledger<br/>UNTRUSTED → TRUSTED → STALE / REFUTED / SUPERSEDED<br/>evidence = doc · page · quote ≤ 40 words · sha256")]
        SCORE["Scoring engine<br/>pure functions · floors · residual band"]
        GW["LLM gateway<br/>budget · breaker · kill switch · redaction · cache · retries"]
    end

    PROV["Providers<br/>rules (default) · Ollama · Google · OpenAI-compatible · Anthropic"]
    PDF["PDF worker<br/>separate process · rlimits · OCR fallback"]
    RET["Retrieval<br/>BM25 + dense → RRF → rerank · tenant-filtered"]
    DB[("Store: SQLite (dev) / Postgres + pgvector + RLS<br/>hash-chained, append-only audit log")]

    USERS --> AUTH
    HOOKS --> AUTH
    AUTH --> A0
    POL --> A0
    A0 --> AG
    AG -- "claims, findings, questions" --> VAL
    VAL --> LED
    LED --> SCORE
    SCORE --> A0
    AG --> GW
    GW --> PROV
    A0 -- "upload" --> PDF
    PDF --> LED
    A4 --> RET
    A0 --> DB
    LED --> DB
```

## 2. End-to-end sequence

```mermaid
sequenceDiagram
    autonumber
    actor SP as Sponsor
    participant WF as A0 Workflow
    participant A1 as A1 Intake
    participant A2 as A2 Screening
    actor AML as AML analyst
    participant A3 as A3 Tiering and scoring
    actor SR as Senior analyst
    participant DP as Doc processor and PDF worker
    participant A4 as A4 Reader (no tools)
    participant VL as Validators and ledger
    participant A10 as A10 Verifier
    actor RV as Reviewer (G3)
    actor AP as Approver (G4)
    participant AU as Audit chain

    SP->>WF: create case (validated intake)
    WF->>AU: CASE_CREATED
    WF->>A1: resolve vendor against master
    A1-->>WF: AUTO_LINK, HUMAN_CONFIRM or NEW_VENDOR
    WF->>A2: screen vendor, directors, owners, subcontractors
    A2-->>WF: recommendations (never a clearance)
    alt potential match or 50% aggregate
        WF->>AML: G1 task, one per match
        AML->>WF: CLEAR or CONFIRM_MATCH with written rationale
        opt match confirmed
            WF->>AU: STATE_CHANGE to REJECTED
        end
    end
    WF->>A3: propose tier from scoring engine
    A3-->>WF: tier, factor breakdown, floors applied
    opt Tier 1 or Tier 2
        WF->>SR: G2 task
        SR->>WF: CONFIRM or OVERRIDE (rationale required)
    end
    loop each required document
        WF->>DP: upload (size, type, hash, sandbox)
        DP-->>WF: clean text, hidden-text and injection flags
    end
    WF->>A4: extract fields from untrusted text
    A4-->>VL: claims with page and verbatim quote
    VL->>VL: locate quote, check value, rewrite legal language
    VL-->>WF: UNTRUSTED claims (ungrounded claims dropped)
    WF->>A10: claims plus fetched passages only
    A10-->>VL: SUPPORTED, or REFUTED / UNSUPPORTED / OVERSTATED
    VL-->>WF: TRUSTED claims only reach scoring
    WF->>A3: rules, control effectiveness, residual band
    A3-->>WF: findings (each cites claims) and band
    WF->>RV: G3 task
    alt approve and no open CRITICAL
        RV->>WF: APPROVE
        WF->>AU: GATE_G3_APPROVE
        WF->>WF: CONTRACTING
        WF->>AP: G4 task (approver set by tier)
        AP->>WF: APPROVE (SoD and open-CRITICAL checks run)
        WF->>AU: STATE_CHANGE to ONBOARDED
        WF->>WF: MONITORING (sweeps, webhooks, material changes)
    else reject
        RV->>WF: REJECT
        WF->>AU: STATE_CHANGE to REJECTED
    else request rework
        RV->>WF: REQUEST_REWORK
        WF->>WF: back to ASSESSMENT
    end
```

## 3. Case state machine

```mermaid
stateDiagram-v2
    [*] --> NEW
    NEW --> INTAKE_REVIEW
    INTAKE_REVIEW --> SCREENING: G0 resolved
    INTAKE_REVIEW --> ON_HOLD
    SCREENING --> TIERING: no potential match
    SCREENING --> HUMAN_SCREEN_REVIEW: potential match (G1)
    HUMAN_SCREEN_REVIEW --> TIERING: all matches dispositioned
    HUMAN_SCREEN_REVIEW --> REJECTED: match confirmed
    TIERING --> DUE_DILIGENCE: tier fixed (G2 for T1 and T2)
    DUE_DILIGENCE --> ASSESSMENT: evidence complete or gaps accepted
    DUE_DILIGENCE --> ON_HOLD
    ON_HOLD --> INTAKE_REVIEW
    ON_HOLD --> DUE_DILIGENCE
    ASSESSMENT --> VERIFICATION
    VERIFICATION --> HUMAN_REVIEW
    VERIFICATION --> ASSESSMENT
    HUMAN_REVIEW --> CONTRACTING: G3 approve
    HUMAN_REVIEW --> REJECTED: G3 reject
    HUMAN_REVIEW --> ASSESSMENT: rework requested
    CONTRACTING --> FINAL_APPROVAL
    FINAL_APPROVAL --> ONBOARDED: G4 approve
    FINAL_APPROVAL --> REJECTED: G4 reject
    ONBOARDED --> MONITORING
    MONITORING --> ASSESSMENT: material change or new evidence
    MONITORING --> OFFBOARDING
    OFFBOARDING --> CLOSED
    REJECTED --> [*]
    CLOSED --> [*]
```

## 4. Claim lifecycle

```mermaid
stateDiagram-v2
    [*] --> UNTRUSTED: agent proposes claim with evidence
    UNTRUSTED --> TRUSTED: verifier says SUPPORTED
    UNTRUSTED --> REFUTED: verifier says UNSUPPORTED, CONTRADICTED or OVERSTATED
    UNTRUSTED --> SUPERSEDED: source document superseded
    TRUSTED --> STALE: ST-001 to ST-010 fires
    STALE --> TRUSTED: re-verified against current source
    STALE --> SUPERSEDED: passage missing from newer document
    STALE --> REFUTED: passage no longer in source
    TRUSTED --> STALE: contradicting evidence added (ST-008)
    REFUTED --> [*]
    SUPERSEDED --> [*]
```
