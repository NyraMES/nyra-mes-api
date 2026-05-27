"""Service layer.

Encapsulates business logic and orchestrates the manufacturing workflow:

    Customer Order
        -> Production Order
        -> Lot Split (sum == order qty)
        -> Routing Generation
        -> Feasibility Validation
        -> Scheduling   (only when feasibility == READY)
        -> Work Order Release   (auto from routing operations)
        -> Production Execution
        -> Inspection   (required after operation completion)
        -> NCR   (auto on failed inspection)
        -> Dispatch   (ops complete + quality passed + no open NCR)
        -> Traceability

Routes import these services - never the other way around.
"""
