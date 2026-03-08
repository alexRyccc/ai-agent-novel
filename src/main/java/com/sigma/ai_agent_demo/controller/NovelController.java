package com.sigma.ai_agent_demo.controller;


import com.sigma.ai_agent_demo.NovelRagService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class NovelController {

    @Autowired
    private NovelRagService novelRagService;

    @GetMapping("/novel/ask")
    public String askNovel(@RequestParam String question) {
        return novelRagService.askNovel(question);
    }
}