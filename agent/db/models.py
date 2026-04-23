from sqlalchemy import (
    Column, 
    Integer, 
    String, 
    Float, 
    Boolean,
    DateTime, 
    ForeignKey, 
    Enum, 
    Text, 
    JSON, 
    Index
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func
import enum
from pgvector.sqlalchemy import Vector

Base = declarative_base()

class LeadStatus(enum.Enum):
    NEW = "new"
    CONTACTED = "contacted"
    REPLIED = "replied"
    QUALIFIED = "qualified"
    BOOKED = "booked"

class ChannelType(enum.Enum):
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    LINKEDIN = "linkedin"

class TimestampMixin:
    """Mixin to add created_at and updated_at to all models."""
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

class Lead(Base, TimestampMixin):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False)
    phone = Column(String(50))
    company = Column(String(255), nullable=False)
    status = Column(Enum(LeadStatus), default=LeadStatus.NEW, nullable=False)
    icp_segment = Column(String(100))
    has_replied_email = Column(Boolean, default=False, nullable=False)

    # Relationships
    enrichments = relationship("Enrichment", back_populates="lead", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="lead", cascade="all, delete-orphan")
    bookings = relationship("Booking", back_populates="lead", cascade="all, delete-orphan")

    # Indices
    __table_args__ = (
        Index("idx_lead_email_company", "email", "company"),
    )

    def __repr__(self):
        return f"<Lead(email='{self.email}', company='{self.company}', status='{self.status}')>"

class Enrichment(Base, TimestampMixin):
    __tablename__ = "enrichments"

    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False)
    signals = Column(JSON, nullable=False, default=dict)
    confidence = Column(Float, default=0.0)

    # Relationships
    lead = relationship("Lead", back_populates="enrichments")

    def __repr__(self):
        return f"<Enrichment(lead_id={self.lead_id}, confidence={self.confidence})>"

class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False)
    channel = Column(Enum(ChannelType), nullable=False)
    message = Column(Text, nullable=False)
    response = Column(Text)
    timestamp = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    lead = relationship("Lead", back_populates="conversations")

    def __repr__(self):
        return f"<Conversation(lead_id={self.lead_id}, channel='{self.channel}')>"

class Booking(Base, TimestampMixin):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False)
    cal_event_id = Column(String(255), unique=True)
    scheduled_at = Column(DateTime, nullable=False)
    status = Column(String(50), default="scheduled")  # e.g., scheduled, completed, cancelled

    # Relationships
    lead = relationship("Lead", back_populates="bookings")

class Company(Base, TimestampMixin):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)
    crunchbase_id = Column(String(255), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    domain = Column(String(255))
    description = Column(Text)
    employee_count = Column(Integer)
    sector = Column(String(100))
    location = Column(String(255))
    country = Column(String(100))
    timezone = Column(String(50))
    funding_round = Column(String(100))
    funding_amount_usd = Column(Float)
    funding_date = Column(DateTime)
    founders_json = Column(JSON, default=dict)
    social_links_json = Column(JSON, default=dict)
    vector_embedding = Column(Vector(1536))

    # Relationships
    signals = relationship("Signal", back_populates="company", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Company(name='{self.name}', domain='{self.domain}')>"

class Signal(Base, TimestampMixin):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    signal_type = Column(String(50), nullable=False)  # e.g., funding, layoff, leadership
    value_json = Column(JSON, nullable=False, default=dict)
    confidence = Column(Float, default=1.0)
    source_url = Column(String(511))

    # Relationships
    company = relationship("Company", back_populates="signals")

    def __repr__(self):
        return f"<Signal(type='{self.signal_type}', confidence={self.confidence})>"
