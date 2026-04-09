SET NAMES utf8mb4;
-- AK 模型白名单关联表
-- 语义：无记录 = 不限制（访问任意模型），有记录 = 白名单（只能访问列表中的模型）
-- 后续扩展：可在 apikey 表增加 model_restrict_enabled 字段，配合本表实现"彻底禁止"语义
CREATE TABLE apikey_model_rel
(
    id         bigint(20)  NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    ak_code    varchar(64) DEFAULT '' NOT NULL COMMENT 'AK编码',
    model_name varchar(64) DEFAULT '' NOT NULL COMMENT '模型名称',
    cuid       bigint(20)  DEFAULT 0  NOT NULL COMMENT '创建人id',
    cu_name    varchar(16) DEFAULT '' NOT NULL COMMENT '创建人姓名',
    ctime      timestamp   DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY `uniq_idx_ak_code_model` (`ak_code`, `model_name`),
    KEY `idx_ak_code` (`ak_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AK模型白名单';