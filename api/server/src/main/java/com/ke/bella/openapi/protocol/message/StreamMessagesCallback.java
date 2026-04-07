package com.ke.bella.openapi.protocol.message;

import com.ke.bella.openapi.EndpointProcessData;
import com.ke.bella.openapi.apikey.ApikeyInfo;
import com.ke.bella.openapi.protocol.completion.StreamCompletionResponse;
import com.ke.bella.openapi.protocol.completion.callback.StreamCompletionCallback;
import com.ke.bella.openapi.protocol.log.EndpointLogger;
import com.ke.bella.openapi.safety.ISafetyCheckService;
import com.ke.bella.openapi.safety.SafetyCheckRequest;
import com.ke.bella.openapi.utils.DateTimeUtils;
import com.ke.bella.openapi.utils.SseHelper;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.collections4.CollectionUtils;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.List;
import java.util.stream.Collectors;

@Slf4j
public class StreamMessagesCallback extends StreamCompletionCallback {

    private boolean first = true;

    private Integer curChoiceIndex = -1;

    private boolean isToolCall;

    private boolean isSendFinish;

    private int stage; // 0 - not started, 1 - thinking, 2 - text, 3 - tool call

    private int contentIndex = -1;

    /** finish_reason 已到达但 usage 尚未到达时，暂存 stopReason，等 usage chunk 再发 message_delta */
    private String pendingStopReason;

    public StreamMessagesCallback(SseEmitter sse,
            EndpointProcessData processData, ApikeyInfo apikeyInfo,
            EndpointLogger logger,
            ISafetyCheckService<SafetyCheckRequest.Chat> safetyService) {
        super(sse, processData, apikeyInfo, logger, safetyService);
    }

    @Override
    public void callback(StreamCompletionResponse msg) {
        if(firstPackageTime == null) {
            firstPackageTime = DateTimeUtils.getCurrentMills();
        }
        if(processData.isNativeSend()) {
            updateBuffer(msg.getStandardFormat() == null ? msg : msg.getStandardFormat());
            return;
        }
        msg.setCreated(DateTimeUtils.getCurrentSeconds());
        if(CollectionUtils.isNotEmpty(msg.getChoices())) {
            StreamCompletionResponse.Choice streamChoice = msg.getChoices().get(0);
            if(CollectionUtils.isNotEmpty(streamChoice.getDelta().getTool_calls())) {
                isToolCall = true;
            }
            if(curChoiceIndex != streamChoice.getIndex()) {
                // tool_call start 时 convertStreamResponse 内部会递增 contentIndex，此处不需要额外递增
                // text/thinking 时需要手动递增，为新 choice 分配起始 index
                if(CollectionUtils.isEmpty(streamChoice.getDelta().getTool_calls())) {
                    contentIndex += 1;
                }
            }
        }
        TransferFromCompletionsUtils.ConversionResult conversionResult = TransferFromCompletionsUtils.convertStreamResponse(msg, isToolCall, contentIndex);
        if(conversionResult == null) {
            return;
        }
        this.contentIndex = conversionResult.newContentIndex;
        // finish_reason 无 usage，暂存 stopReason，等待 usage chunk
        if(conversionResult.pendingStopReason != null && !isSendFinish) {
            this.pendingStopReason = conversionResult.pendingStopReason;
            // 发出 contentBlockStop，结束当前 block
            if(!first) {
                send(StreamMessageResponse.contentBlockStop(contentIndex));
            }
            isSendFinish = true;
        }
        List<StreamMessageResponse> messages = conversionResult.events;
        // only-usage chunk 到来时，用暂存的 stopReason 替换猜测的 stopReason
        if(pendingStopReason != null && CollectionUtils.isEmpty(msg.getChoices()) && msg.getUsage() != null) {
            for (StreamMessageResponse m : messages) {
                if("message_delta".equals(m.getType()) && m.getDelta() instanceof StreamMessageResponse.MessageDeltaInfo) {
                    ((StreamMessageResponse.MessageDeltaInfo) m.getDelta()).setStopReason(pendingStopReason);
                }
            }
        }
        if(CollectionUtils.isNotEmpty(messages)) {
            if(first) {
                send(StreamMessageResponse.messageStart(StreamMessageResponse.initial(msg, processData.getModel())));
                first = false;
            }
            if(CollectionUtils.isNotEmpty(msg.getChoices())) {
                StreamCompletionResponse.Choice streamChoice = msg.getChoices().get(0);
                if(curChoiceIndex != streamChoice.getIndex()) {
                    if(curChoiceIndex >= 0) {
                        send(StreamMessageResponse.contentBlockStop(contentIndex - 1));
                    }
                    if(!messages.get(0).getType().equals("content_block_start")) {
                        MessageResponse.ContentBlock contentBlock;
                        if(streamChoice.getDelta().getReasoning_content() != null
                                || streamChoice.getDelta().getReasoning_content_signature() != null) {
                            contentBlock = new MessageResponse.ResponseThinkingBlock("", null);
                        } else {
                            contentBlock = new MessageResponse.ResponseTextBlock("");
                        }
                        send(StreamMessageResponse.contentBlockStart(contentIndex, contentBlock));
                    }
                    curChoiceIndex = streamChoice.getIndex();
                    stage = getCurrentStage(streamChoice);
                } else {
                    int currentStage = getCurrentStage(streamChoice);
                    if(stage == 3 && currentStage == 3) {
                        if(messages.get(0).getType().equals("content_block_start")) {
                            int index = getTargetIndex(messages, stage);
                            messages.add(index, StreamMessageResponse.contentBlockStop(contentIndex - 1));
                            curChoiceIndex += 1;
                        }
                    } else if(currentStage != stage) {
                        stage = currentStage;
                        int index = getTargetIndex(messages, stage);
                        if(currentStage != 3) {
                            // tool call 到 text/thinking 的切换：需要自行递增 contentIndex 并生成 content_block_start
                            contentIndex += 1;
                            MessageResponse.ContentBlock contentBlock = currentStage == 2 ? new MessageResponse.ResponseTextBlock("")
                                    : new MessageResponse.ResponseThinkingBlock("", null);;
                            messages.add(index, StreamMessageResponse.contentBlockStart(contentIndex, contentBlock));
                            messages.forEach(streamMessageResponse -> {
                                if(!"message_delta".equals(streamMessageResponse.getType())) {
                                    streamMessageResponse.setIndex(contentIndex);
                                }
                            });
                        }
                        // currentStage == 3 时，convertStreamResponse 已经递增了 contentIndex 并生成 content_block_start
                        // 只需添加前一个 block 的 stop（用当前 contentIndex - 1，因为 convertStreamResponse 已经递增了）
                        messages.add(index, StreamMessageResponse.contentBlockStop(contentIndex - 1));
                    }
                }
            }

            if(messages.get(messages.size() - 1).getType().equals("message_delta") && !isSendFinish) {
                // finish_reason 和 usage 在同一 chunk：正常流程，插入 contentBlockStop 后发 message_delta
                isSendFinish = true;
                messages.add(messages.size() - 1, StreamMessageResponse.contentBlockStop(contentIndex));
            } else if(messages.get(messages.size() - 1).getType().equals("message_delta") && pendingStopReason != null) {
                // only-usage chunk：pendingStopReason 已处理，允许此 message_delta 发出，清空 pending
                pendingStopReason = null;
            } else if(isSendFinish) {
                // isSendFinish 已为 true 且没有待发的 message_delta，过滤掉重复的 message_delta
                messages = messages.stream()
                        .filter(m -> !"message_delta".equals(m.getType()))
                        .collect(Collectors.toList());
            }
            messages.forEach(this::send);
        }
        updateBuffer(msg.getStandardFormat() == null ? msg : msg.getStandardFormat());
    }

    private int getCurrentStage(StreamCompletionResponse.Choice streamChoice) {
        return streamChoice.getDelta() == null ? 0
                : streamChoice.getDelta().getTool_calls() != null ? 3
                        : streamChoice.getDelta().getContent() != null ? 2
                                : streamChoice.getDelta().getReasoning_content() != null
                                        || streamChoice.getDelta().getReasoning_content_signature() != null
                                        || streamChoice.getDelta().getRedacted_reasoning_content() != null
                                                ? 1
                                                : 0;
    }

    private int getTargetIndex(List<StreamMessageResponse> messages, int stage) {
        for (int i = 0; i < messages.size(); i++) {
            StreamMessageResponse message = messages.get(i);
            if(message.getType().equals("content_block_start")) {
                return i;
            }
            Object delta = message.getDelta();
            if(stage == 2) {
                if(!(delta instanceof StreamMessageResponse.TextDelta)) {
                    return i;
                }
            }
            if(stage == 1) {
                if(!(delta instanceof StreamMessageResponse.ThinkingDelta || delta instanceof StreamMessageResponse.SignatureDelta
                        || delta instanceof StreamMessageResponse.RedactedThinkingDelta)) {
                    return i;
                }
            }
        }
        return 0;
    }

    @Override
    public void done() {
        if(processData.isNativeSend()) {
            return;
        }
        if(!isSendFinish) {
            send(StreamMessageResponse.contentBlockStop(contentIndex));
            StreamMessageResponse.StreamUsage streamUsage = StreamMessageResponse.StreamUsage.builder()
                    .outputTokens(1)
                    .inputTokens(1)
                    .build();
            String stopReason = pendingStopReason != null ? pendingStopReason : (isToolCall ? "tool_use" : "end_turn");
            StreamMessageResponse.MessageDeltaInfo messageInfo = StreamMessageResponse.MessageDeltaInfo.builder()
                    .stopReason(stopReason)
                    .build();
            send(StreamMessageResponse.messageDelta(messageInfo, streamUsage));
        } else if(pendingStopReason != null) {
            // finish_reason 已处理但 usage chunk 始终未到，兜底发一个 message_delta
            StreamMessageResponse.StreamUsage streamUsage = StreamMessageResponse.StreamUsage.builder()
                    .outputTokens(1)
                    .inputTokens(1)
                    .build();
            StreamMessageResponse.MessageDeltaInfo messageInfo = StreamMessageResponse.MessageDeltaInfo.builder()
                    .stopReason(pendingStopReason)
                    .build();
            send(StreamMessageResponse.messageDelta(messageInfo, streamUsage));
        }
        send(StreamMessageResponse.messageStop());
    }

    @Override
    public void send(Object data) {
        if(sse == null) {
            return;
        }
        if(data instanceof StreamMessageResponse) {
            SseHelper.sendEvent(sse, ((StreamMessageResponse) data).getType(), data);
        } else {
            throw new IllegalStateException("Only Support StreamMessageResponse");
        }
    }

}
