package com.sigma.ai_agent_demo.nove;

import org.springframework.ai.document.Document;
import org.springframework.ai.reader.tika.TikaDocumentReader;
import org.springframework.ai.transformer.splitter.TokenTextSplitter;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.Resource;
import org.springframework.core.io.support.PathMatchingResourcePatternResolver;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import jakarta.annotation.PostConstruct;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

@Component
public class NovelDocumentLoader {

    @Autowired
    private VectorStore vectorStore;

    // 小说文件存放路径，支持 classpath*: 或 file: 前缀
    @Value("${novel.location:classpath:novels/*.docx}")
    private String novelLocation;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Value("${app.load-documents-on-startup:true}")
    private boolean loadDocumentsOnStartup;

    @PostConstruct
    public void loadNovels() {

        if (!loadDocumentsOnStartup) {
            System.out.println("根据配置跳过文档加载。");
            return;
        }

        // 检查是否已有数据
        String sql = "SELECT COUNT(*) FROM vector_store";
        Integer count = jdbcTemplate.queryForObject(sql, Integer.class);
        if (count != null && count > 0) {
            System.out.println("向量库中已有 " + count + " 条记录，跳过文档加载。");
            return;
        }

        System.out.println("开始加载小说文件...");
        PathMatchingResourcePatternResolver resolver = new PathMatchingResourcePatternResolver();
        try {
            Resource[] resources = resolver.getResources(novelLocation);
            if (resources.length == 0) {
                System.out.println("未找到任何小说文件，请检查路径配置：" + novelLocation);
                return;
            }

            List<Document> allDocuments = new ArrayList<>();
            for (Resource resource : resources) {
                System.out.println("正在处理：" + resource.getFilename());
                TikaDocumentReader reader = new TikaDocumentReader(resource);
                List<Document> docs = reader.get();

                TokenTextSplitter splitter = TokenTextSplitter.builder()
                        .withChunkSize(500)
                        .withMinChunkSizeChars(350)
                        .withMinChunkLengthToEmbed(5)
                        .withMaxNumChunks(10000)
                        .withKeepSeparator(true)
                        .build();

                List<Document> splitDocs = splitter.apply(docs);
                allDocuments.addAll(splitDocs);
                System.out.println("文件 " + resource.getFilename() + " 切分为 " + splitDocs.size() + " 个片段");
            }

            // 分批存入向量库（每批最多 10 个）
            int batchSize = 10;
            for (int i = 0; i < allDocuments.size(); i += batchSize) {
                int end = Math.min(i + batchSize, allDocuments.size());
                List<Document> batch = allDocuments.subList(i, end);
                vectorStore.add(batch);
                System.out.println("已存入第 " + (i / batchSize + 1) + " 批，共 " + batch.size() + " 个片段");
            }

            System.out.println("所有小说已加载完成，共 " + allDocuments.size() + " 个片段");

        } catch (IOException e) {
            System.err.println("读取小说文件失败：" + e.getMessage());
            e.printStackTrace();
        }
    }
}