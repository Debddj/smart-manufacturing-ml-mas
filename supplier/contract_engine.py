"""
ContractEngine — Smart Contract Agreement layer from the architecture diagram.

Architecture position:
    Supplier Node Network → Smart Contract Agreement

Simulates automated contract issuance for supplier procurement.
In a production system this would interface with a blockchain or
ERP contract management system.
"""

from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class Contract:
    """A single procurement contract between the system and a supplier."""
    contract_id:  str
    supplier_id:  str
    units:        float
    cost:         float
    lead_time:    int
    issued_at:    str
    status:       str = "ACTIVE"    # ACTIVE | FULFILLED | CANCELLED | EXPIRED

    def fulfil(self) -> None:
        self.status = "FULFILLED"

    def cancel(self) -> None:
        self.status = "CANCELLED"

    def to_dict(self) -> dict:
        return {
            "contract_id": self.contract_id,
            "supplier_id": self.supplier_id,
            "units":       round(self.units, 1),
            "cost":        round(self.cost,  2),
            "lead_time":   self.lead_time,
            "issued_at":   self.issued_at,
            "status":      self.status,
        }


class ContractEngine:
    """
    Issues and tracks smart procurement contracts.

    Provides:
        - Contract issuance with unique IDs
        - Status tracking (ACTIVE / FULFILLED / CANCELLED)
        - Episode cost and fulfilment summaries
    """

    def __init__(self, agent_name: str = "SmartContractEngine"):
        self.name           = agent_name
        self.contracts:     List[Contract] = []
        self.contract_count = 0

    def issue_contract(
        self,
        supplier_id: str,
        units:       float,
        cost:        float,
        lead_time:   int = 1,
    ) -> dict:
        """
        Issue a new procurement contract.

        Returns:
            Contract dict suitable for logging and dashboard display.
        """
        self.contract_count += 1
        cid = f"CTR-{self.contract_count:05d}-{str(uuid.uuid4())[:6].upper()}"

        contract = Contract(
            contract_id = cid,
            supplier_id = supplier_id,
            units       = units,
            cost        = cost,
            lead_time   = lead_time,
            issued_at   = datetime.now().strftime("%H:%M:%S"),
        )
        self.contracts.append(contract)
        return contract.to_dict()

    def fulfil_contract(self, contract_id: str) -> bool:
        """Mark a contract as fulfilled. Returns True if found."""
        for c in self.contracts:
            if c.contract_id == contract_id:
                c.fulfil()
                return True
        return False

    def total_contracted_value(self) -> float:
        return sum(c.cost for c in self.contracts)

    def active_contracts(self) -> List[dict]:
        return [c.to_dict() for c in self.contracts if c.status == "ACTIVE"]

    def snapshot(self) -> dict:
        return {
            "contract_count":       self.contract_count,
            "active_contracts":     len(self.active_contracts()),
            "total_contract_value": round(self.total_contracted_value(), 2),
        }

    def reset(self) -> None:
        self.contracts     = []
        self.contract_count = 0 