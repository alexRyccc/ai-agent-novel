package com.sigma.ai_agent_demo;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.chat.prompt.SystemPromptTemplate;
import org.springframework.ai.document.Document;
import org.springframework.ai.embedding.EmbeddingModel;
import org.springframework.ai.vectorstore.SearchRequest;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Service
public class NovelRagService {
    private static final Logger log = LoggerFactory.getLogger(NovelRagService.class);
    private final ChatClient chatClient;
    @Autowired private VectorStore vectorStore;

    @Autowired
    private EmbeddingModel embeddingModel;

    public NovelRagService(ChatClient.Builder chatClientBuilder) {
        this.chatClient = chatClientBuilder.build();
    }

    public String askNovel(String question) {
        log.info("EmbeddingModel dimensions: {}", embeddingModel.dimensions());

        log.info("用户问题: {}", question);

        // 构建检索请求，显式设置阈值为0（不接受过滤）
        SearchRequest request = SearchRequest.builder()
                .query(question)
                .topK(20)
                .similarityThreshold(1.0) // 显式设为0
                .build();
        log.debug("SearchRequest: {}", request);

        long startRetrieval = System.currentTimeMillis();
        List<Document> similarDocs = vectorStore.similaritySearch(request);
        long retrievalTime = System.currentTimeMillis() - startRetrieval;
        log.info("检索耗时: {} ms, 结果数: {}", retrievalTime, similarDocs.size());

        if (similarDocs.isEmpty()) {
            log.warn("未检索到相关文档");
            return "抱歉，没有找到相关信息。";
        }

        // 打印检索片段
        for (int i = 0; i < similarDocs.size(); i++) {
            Document doc = similarDocs.get(i);
            log.debug("片段{} (距离忽略): 预览: {}...", i+1,
                    doc.getText().length() > 100 ? doc.getText().substring(0,100) : doc.getText());
            log.debug("元数据: {}", doc.getMetadata());
        }

        String context = similarDocs.stream().map(Document::getText)
                .collect(Collectors.joining("\n\n---\n\n"));

        SystemPromptTemplate systemPrompt = new SystemPromptTemplate("""
                你是一个小说智能助手。以下是用户问题相关的多个小说片段（按相关性排序），请仔细阅读并综合这些片段，尽可能全面、准确地回答用户的问题。
                如果片段中有矛盾或不一致的信息，请指出并基于多数或合理推测回答。
                如果所有片段中都没有相关信息，请说明“未找到相关信息”。
                片段：
                {context}
                """);
        Message systemMsg = systemPrompt.createMessage(Map.of("context", context));
        Prompt prompt = new Prompt(List.of(systemMsg, new UserMessage(question)));

        log.debug("发送给模型的 Prompt: {}", prompt.getContents());

        long startLLM = System.currentTimeMillis();
        String answer;
        try {
            answer = chatClient.prompt(prompt).call().content();
        } catch (Exception e) {
            log.error("模型调用失败", e);
            return "模型调用失败，请稍后重试。";
        }
        long llmTime = System.currentTimeMillis() - startLLM;
        log.info("模型调用耗时: {} ms", llmTime);
        log.info("模型回答: {}", answer);
        return answer;
    }
}