"""KAI Capability Fabric — governed capability discovery, routing, and lifecycle.

KAI is the brain. Everything here is a capability KAI can call when useful, behind one
registry, one decision brain, and one governance gate. Pure-logic modules (no FastAPI / DB
import at package load) so the core is testable as plain ``python3`` scripts.
"""
