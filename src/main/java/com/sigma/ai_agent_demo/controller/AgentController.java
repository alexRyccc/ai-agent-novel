package com.sigma.ai_agent_demo.controller;

import com.sigma.ai_agent_demo.AgentService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class AgentController {

    private final AgentService agentService;

    public AgentController(AgentService agentService) {
        this.agentService = agentService;
    }

    @GetMapping("/ai/chat")
    public String chat(@RequestParam String message) {
        return agentService.chat(message);
    }
}