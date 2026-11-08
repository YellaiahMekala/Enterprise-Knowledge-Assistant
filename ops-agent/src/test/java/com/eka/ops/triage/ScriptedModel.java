package com.eka.ops.triage;

import dev.langchain4j.agent.tool.ToolExecutionRequest;
import dev.langchain4j.data.message.AiMessage;
import dev.langchain4j.data.message.ChatMessage;
import dev.langchain4j.data.message.ToolExecutionResultMessage;
import dev.langchain4j.model.chat.ChatModel;
import dev.langchain4j.model.chat.request.ChatRequest;
import dev.langchain4j.model.chat.response.ChatResponse;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;
import java.util.Queue;

/** A model that plays back prepared replies, so the agent loop can be tested without a network. */
final class ScriptedModel implements ChatModel {

    private final Queue<AiMessage> script = new ArrayDeque<>();
    final List<ChatRequest> requests = new ArrayList<>();

    ScriptedModel then(AiMessage reply) {
        script.add(reply);
        return this;
    }

    static AiMessage callTool(String id, String tool, String jsonArguments) {
        return AiMessage.from(ToolExecutionRequest.builder().id(id).name(tool).arguments(jsonArguments).build());
    }

    static AiMessage answer(String json) {
        return AiMessage.from(json);
    }

    /** Text of every tool result the agent has sent back to the model so far. */
    List<String> toolResultsSeen() {
        List<String> seen = new ArrayList<>();
        for (ChatRequest request : requests) {
            for (ChatMessage message : request.messages()) {
                if (message instanceof ToolExecutionResultMessage result && !seen.contains(result.text())) {
                    seen.add(result.text());
                }
            }
        }
        return seen;
    }

    @Override
    public ChatResponse doChat(ChatRequest request) {
        requests.add(request);
        AiMessage next = script.poll();
        if (next == null) {
            throw new IllegalStateException("the script has no more replies");
        }
        return ChatResponse.builder().aiMessage(next).build();
    }
}
