package com.ke.bella.openapi.db.repo;

import com.ke.bella.openapi.Operator;
import org.jooq.DSLContext;
import org.jooq.Field;
import org.jooq.Table;
import org.jooq.impl.DSL;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import javax.annotation.Resource;
import java.util.LinkedHashSet;
import java.util.List;

@Component
public class ApikeyModelRelRepo {

    @Resource
    protected DSLContext db;

    private static final Table<?> TABLE = DSL.table("apikey_model_rel");
    private static final Field<String> AK_CODE = DSL.field("ak_code", String.class);
    private static final Field<String> MODEL_NAME = DSL.field("model_name", String.class);
    private static final Field<Long> CUID = DSL.field("cuid", Long.class);
    private static final Field<String> CU_NAME = DSL.field("cu_name", String.class);

    public List<String> listModelsByAkCode(String akCode) {
        return db.select(MODEL_NAME)
                .from(TABLE)
                .where(AK_CODE.eq(akCode))
                .fetch(MODEL_NAME);
    }

    @Transactional
    public void replaceModels(String akCode, List<String> modelNames, Operator operator) {
        db.deleteFrom(TABLE)
                .where(AK_CODE.eq(akCode))
                .execute();
        if (modelNames != null && !modelNames.isEmpty()) {
            Long cuid = (operator != null && operator.getUserId() != null) ? operator.getUserId() : 0L;
            String cuName = (operator != null && operator.getUserName() != null) ? operator.getUserName() : "";
            // 去重，避免重复模型名触发 UNIQUE KEY 冲突
            for (String modelName : new LinkedHashSet<>(modelNames)) {
                db.insertInto(TABLE)
                        .set(AK_CODE, akCode)
                        .set(MODEL_NAME, modelName)
                        .set(CUID, cuid)
                        .set(CU_NAME, cuName)
                        .execute();
            }
        }
    }

    @Transactional
    public void addModels(String akCode, List<String> modelNames, Operator operator) {
        Long cuid = (operator != null && operator.getUserId() != null) ? operator.getUserId() : 0L;
        String cuName = (operator != null && operator.getUserName() != null) ? operator.getUserName() : "";
        for (String modelName : modelNames) {
            db.insertInto(TABLE)
                    .set(AK_CODE, akCode)
                    .set(MODEL_NAME, modelName)
                    .set(CUID, cuid)
                    .set(CU_NAME, cuName)
                    .execute();
        }
    }

    @Transactional
    public void removeModels(String akCode, List<String> modelNames) {
        db.deleteFrom(TABLE)
                .where(AK_CODE.eq(akCode))
                .and(MODEL_NAME.in(modelNames))
                .execute();
    }

    @Transactional
    public void deleteByAkCode(String akCode) {
        db.deleteFrom(TABLE)
                .where(AK_CODE.eq(akCode))
                .execute();
    }

    // TODO: 当前系统无 AK 物理删除接口，AK inactivate 时白名单记录保留，activate 后继续有效。
    // 若未来新增 AK 物理删除功能，需在删除 AK 时级联调用 deleteByAkCode(akCode) 清理白名单记录，
    // 同时也需处理其所有子 AK 的白名单记录。
}
