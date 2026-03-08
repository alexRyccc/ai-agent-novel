package com.sigma.ai_agent_demo.tool;

import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;

public class WeatherTools {

    @Tool(description = "获取指定城市的当前天气信息") // 描述对AI至关重要，帮助它理解何时调用
    public String getWeather(@ToolParam(description = "城市名称")String city){
        System.out.println("--- 工具被调用，查询城市: " + city + " ---");
        return city + " 今天多云，气温 15-22℃，空气质量优。";
    }


}
