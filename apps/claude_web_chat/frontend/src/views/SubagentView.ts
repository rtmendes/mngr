import m from "mithril";
import { apiUrl } from "../base-path";
import { MarkdownContent } from "../markdown";
import type { TranscriptEvent, ToolCall, SubagentMetadata } from "../models/Response";

interface SubagentViewAttrs {
  agentId: string;
  subagentSessionId: string;
}

interface SubagentEventsResponse {
  events: TranscriptEvent[];
  metadata: SubagentMetadata | null;
}

function renderUserMessage(event: TranscriptEvent): m.Vnode {
  return m("div", { class: "message message-user", key: event.event_id }, [
    m("div", { class: "message-user-bubble" }, [
      m("div", { class: "message-content whitespace-pre-wrap" }, event.content || ""),
    ]),
  ]);
}

function renderSubagentCard(toolCall: ToolCall, agentId: string): m.Vnode {
  const metadata = toolCall.subagent_metadata;
  if (!metadata) {
    return renderToolCallBlock(toolCall, null);
  }

  const description = metadata.description || "Sub-agent";
  const agentType = metadata.agent_type || "";
  const subagentUrl = `#!/agents/${encodeURIComponent(agentId)}/subagents/${encodeURIComponent(metadata.session_id)}`;

  return m("div", { class: "subagent-card" }, [
    m("div", { class: "subagent-card-header" }, [
      m("span", { class: "subagent-card-description" }, description),
      agentType ? m("span", { class: "subagent-card-type-badge" }, agentType) : null,
    ]),
    m(
      "a",
      {
        class: "subagent-card-link",
        href: subagentUrl,
        target: "_blank",
        rel: "noopener",
        onclick(e: Event) {
          e.stopPropagation();
        },
      },
      "View conversation \u2197",
    ),
  ]);
}

function renderToolCallBlock(toolCall: ToolCall, toolResult: TranscriptEvent | null): m.Vnode {
  const headerText = `Tool: ${toolCall.tool_name}`;
  const inputText = toolCall.input_preview || "";
  const outputText = toolResult?.output || "";
  const isError = toolResult?.is_error === true;

  return m("div", { class: "tool-call-block" }, [
    m(
      "div",
      {
        class: "tool-call-header",
        onclick(e: Event) {
          const block = (e.currentTarget as HTMLElement).parentElement;
          if (block) {
            block.classList.toggle("tool-call-block--expanded");
          }
        },
      },
      [m("span", { class: "tool-call-chevron" }, "\u25B8"), m("span", headerText)],
    ),
    m("div", { class: "tool-call-details" }, [
      inputText ? m("div", { class: "tool-call-input" }, [m("pre", m("code", inputText))]) : null,
      outputText
        ? m("div", { class: isError ? "tool-call-output tool-call-output--error" : "tool-call-output" }, [
            m("pre", m("code", outputText)),
          ])
        : null,
    ]),
  ]);
}

function renderAssistantMessage(
  event: TranscriptEvent,
  toolResults: Map<string, TranscriptEvent>,
  agentId: string,
): m.Vnode {
  const textContent = event.text || "";
  const toolCalls = event.tool_calls || [];

  const children: m.Children[] = [];
  if (textContent) {
    children.push(m(MarkdownContent, { content: textContent }));
  }
  for (const toolCall of toolCalls) {
    if (toolCall.tool_name === "Agent" && toolCall.subagent_metadata) {
      children.push(renderSubagentCard(toolCall, agentId));
    } else {
      const result = toolResults.get(toolCall.tool_call_id) ?? null;
      children.push(renderToolCallBlock(toolCall, result));
    }
  }

  return m(
    "div",
    { id: event.event_id, class: "message message-assistant", key: event.event_id },
    m("div", children),
  );
}

export function SubagentView(): m.Component<SubagentViewAttrs> {
  let events: TranscriptEvent[] = [];
  let metadata: SubagentMetadata | null = null;
  let loading = true;
  let loadingError: string | null = null;
  let eventSource: EventSource | null = null;

  async function fetchSubagentEvents(agentId: string, subagentSessionId: string): Promise<void> {
    loading = true;
    loadingError = null;

    try {
      const result = await m.request<SubagentEventsResponse>({
        method: "GET",
        url: apiUrl(`/api/agents/${encodeURIComponent(agentId)}/subagents/${encodeURIComponent(subagentSessionId)}/events`),
      });
      events = result.events;
      metadata = result.metadata ?? null;
      loading = false;
    } catch (error) {
      loading = false;
      loadingError = (error as Error).message ?? String(error);
    }
  }

  function connectToStream(agentId: string, subagentSessionId: string): void {
    if (eventSource !== null) {
      return;
    }

    const url = apiUrl(
      `/api/agents/${encodeURIComponent(agentId)}/subagents/${encodeURIComponent(subagentSessionId)}/stream`,
    );
    eventSource = new EventSource(url);

    eventSource.onmessage = (messageEvent: MessageEvent) => {
      const event = JSON.parse(messageEvent.data) as TranscriptEvent;
      const existingIds = new Set(events.map((e) => e.event_id));
      if (!existingIds.has(event.event_id)) {
        events = [...events, event];
        m.redraw();
      }
    };

    eventSource.onerror = () => {
      if (eventSource !== null) {
        eventSource.close();
        eventSource = null;
      }
    };
  }

  function disconnectFromStream(): void {
    if (eventSource !== null) {
      eventSource.close();
      eventSource = null;
    }
  }

  return {
    oninit(vnode) {
      const { agentId, subagentSessionId } = vnode.attrs;
      fetchSubagentEvents(agentId, subagentSessionId).then(() => {
        connectToStream(agentId, subagentSessionId);
      });
    },

    onremove() {
      disconnectFromStream();
    },

    view(vnode) {
      const { agentId } = vnode.attrs;
      const title = metadata?.description || "Sub-agent conversation";
      const agentType = metadata?.agent_type || "";

      const header = m("header", { class: "app-header" }, [
        m("h1", { class: "app-header-title" }, title),
        agentType ? m("span", { class: "app-header-model-badge" }, agentType) : null,
      ]);

      let content: m.Vnode;

      if (loading) {
        content = m(
          "div",
          { class: "message-list-loading flex items-center justify-center h-full" },
          m("p", { class: "text-text-secondary" }, "Loading events..."),
        );
      } else if (loadingError) {
        content = m(
          "div",
          { class: "message-list-error flex items-center justify-center h-full" },
          m("p", { class: "text-red-500" }, `Error: ${loadingError}`),
        );
      } else if (events.length === 0) {
        content = m(
          "div",
          { class: "message-list-empty flex items-center justify-center h-full" },
          m("p", { class: "text-text-secondary" }, "No events yet."),
        );
      } else {
        const toolResults = new Map<string, TranscriptEvent>();
        for (const event of events) {
          if (event.type === "tool_result" && event.tool_call_id) {
            toolResults.set(event.tool_call_id, event);
          }
        }

        const messageNodes: m.Vnode[] = [];
        for (const event of events) {
          if (event.type === "user_message") {
            messageNodes.push(renderUserMessage(event));
          } else if (event.type === "assistant_message") {
            messageNodes.push(renderAssistantMessage(event, toolResults, agentId));
          }
        }

        content = m("div", { class: "message-list-wrapper" }, [
          m(
            "div",
            { class: "message-list mx-auto w-full max-w-(--width-message-column) flex flex-col py-6" },
            messageNodes,
          ),
        ]);
      }

      return m("div", { class: "app-content-wrapper flex-1 flex flex-col min-h-0" }, [
        header,
        m("main", { class: "app-content flex-1 overflow-y-auto px-8 py-6" }, content),
        // No footer/message input -- read-only
      ]);
    },
  };
}
