// The watch namespace's types: a session's live view and the hand a person takes in it. An app names each
// as watch.<Name>, through the package's entry.
import type { components } from "../schema/watch";

type Schemas = components["schemas"];

export type CommandProgressView = Schemas["CommandProgressView"];
export type CommandRequest = Schemas["CommandRequest"];
export type ControlGiveBackRequest = Schemas["ControlGiveBackRequest"];
export type HandRunView = Schemas["HandRunView"];
export type LivePageView = Schemas["LivePageView"];
export type LivePartView = Schemas["LivePartView"];
export type LiveReadView = Schemas["LiveReadView"];
export type LiveStreamView = Schemas["LiveStreamView"];
