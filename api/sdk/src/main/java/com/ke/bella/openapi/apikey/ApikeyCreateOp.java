package com.ke.bella.openapi.apikey;

import com.ke.bella.openapi.Operator;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;
import lombok.experimental.SuperBuilder;

import java.math.BigDecimal;
import java.util.List;

@Data
@SuperBuilder
@AllArgsConstructor
@NoArgsConstructor
public class ApikeyCreateOp extends Operator {
    private String name;
    private String parentCode;
    private Byte safetyLevel;
    private String outEntityCode;
    private BigDecimal monthQuota;
    private String roleCode;
    private List<String> paths;
    private String remark;
    /**
     * 子 AK 模型白名单。
     * null = 自动继承父 AK 白名单；
     * 空列表 = 显式不限制（仅在父 AK 无白名单时合法）；
     * 非空列表 = 必须是父 AK 白名单的子集
     */
    private List<String> allowedModels;
}
