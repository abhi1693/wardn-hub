from dataclasses import dataclass


@dataclass(frozen=True)
class EventTypeDefinition:
    event_type: str
    label: str
    description: str
    subject_type: str


EVENT_TYPES: tuple[EventTypeDefinition, ...] = (
    EventTypeDefinition(
        event_type="submission.created",
        label="Submission created",
        description="A server submission draft was created.",
        subject_type="server_submission",
    ),
    EventTypeDefinition(
        event_type="submission.updated",
        label="Submission updated",
        description="A server submission draft was updated.",
        subject_type="server_submission",
    ),
    EventTypeDefinition(
        event_type="submission.submitted",
        label="Submission submitted",
        description="A server submission was submitted for review.",
        subject_type="server_submission",
    ),
    EventTypeDefinition(
        event_type="submission.withdrawn",
        label="Submission withdrawn",
        description="A submitted server submission was withdrawn.",
        subject_type="server_submission",
    ),
    EventTypeDefinition(
        event_type="submission.approved",
        label="Submission approved",
        description="A server submission was approved.",
        subject_type="server_submission",
    ),
    EventTypeDefinition(
        event_type="submission.rejected",
        label="Submission rejected",
        description="A server submission was rejected.",
        subject_type="server_submission",
    ),
    EventTypeDefinition(
        event_type="submission.published",
        label="Submission published",
        description="An approved server submission was published.",
        subject_type="server_submission",
    ),
    EventTypeDefinition(
        event_type="submission.deleted",
        label="Submission deleted",
        description="A server submission was deleted.",
        subject_type="server_submission",
    ),
    EventTypeDefinition(
        event_type="registry.server.published",
        label="Registry server published",
        description="A registry server was published.",
        subject_type="registry_server",
    ),
    EventTypeDefinition(
        event_type="registry.server.archived",
        label="Registry server archived",
        description="A registry server was archived.",
        subject_type="registry_server",
    ),
    EventTypeDefinition(
        event_type="registry.version.published",
        label="Registry version published",
        description="A registry server version was published.",
        subject_type="registry_server_version",
    ),
)

EVENT_TYPE_BY_NAME = {definition.event_type: definition for definition in EVENT_TYPES}


def is_supported_event_type(event_type: str) -> bool:
    return event_type in EVENT_TYPE_BY_NAME
