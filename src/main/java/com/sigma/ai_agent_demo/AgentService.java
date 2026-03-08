package com.sigma.ai_agent_demo;

import com.sigma.ai_agent_demo.tool.WeatherTools;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.support.ToolCallbacks;
import org.springframework.stereotype.Service;

@Service
public class AgentService {
    private final ChatClient chatClient;

    public AgentService(ChatClient.Builder builder) {
        this.chatClient = builder
                .defaultToolCallbacks(ToolCallbacks.from(new WeatherTools()))
                .build()
        ;
    }

    public String chat(String message) {
        return chatClient.prompt()
                .user(message) // 设置用户消息
                .call()        // 发起同步调用
                .content();     // 获取返回内容
    }
}
