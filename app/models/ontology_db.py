"""DB-side ontology metadata: ref.ontology_class, ref.ontology_relationship,
ref.entity_ontology_mapping, and the trn.rdf_triple_staging buffer.

These complement the hard-coded ontology constants in
``app.core.ontology`` - the DB tables let domain owners extend the
manufacturing ontology without a code change, and the staging table is the
write-target when we materialise RDF triples for SPARQL export.
"""

from sqlalchemy import (
    BigInteger,
    Column,
    String,
    TIMESTAMP,
    Text,
)
from sqlalchemy.sql import func

from app.db.base import Base


class OntologyClass(Base):
    __tablename__ = "ontology_class"
    __table_args__ = {"schema": "ref"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    class_name = Column(String, nullable=False, unique=True)
    domain_area = Column(String)
    description = Column(Text)


class OntologyRelationship(Base):
    __tablename__ = "ontology_relationship"
    __table_args__ = {"schema": "ref"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    predicate_name = Column(String, nullable=False)
    subject_class = Column(String)
    object_class = Column(String)
    description = Column(Text)


class EntityOntologyMapping(Base):
    __tablename__ = "entity_ontology_mapping"
    __table_args__ = {"schema": "ref"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source_schema = Column(String)
    source_table = Column(String)
    source_column = Column(String)
    ontology_class = Column(String)
    ontology_property = Column(String)
    created_at = Column(TIMESTAMP, server_default=func.now())


class RDFTripleStaging(Base):
    __tablename__ = "rdf_triple_staging"
    __table_args__ = {"schema": "trn"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    subject_uri = Column(Text, nullable=False)
    predicate_uri = Column(Text, nullable=False)
    object_uri_or_value = Column(Text, nullable=False)
    object_type = Column(String)
    source_table = Column(String)
    source_record_id = Column(String)
    created_at = Column(TIMESTAMP, server_default=func.now())
