'use client'

import React, { useState, useEffect, useCallback } from 'react'
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Alert, AlertDescription } from "@/components/ui/alert"
import {
    AlertCircle,
    X,
    Plus,
    ShieldCheck,
    ShieldOff,
    Loader2,
    TriangleAlert,
} from "lucide-react"
import { useToast } from "@/hooks/use-toast"
import { getAllowedModels, addAllowedModels, removeAllowedModels, replaceAllowedModels } from "@/lib/api/apikey"
import { listConsoleModels } from "@/lib/api/meta"

interface AllowedModelsDialogProps {
    isOpen: boolean
    onClose: () => void
    akCode: string
    akName?: string
    /** 父 AK 白名单，用于限制子 AK 可选范围（主 AK 无需传入） */
    parentAllowedModels?: string[]
    onSuccess?: (newModels: string[]) => void
}

export const AllowedModelsDialog: React.FC<AllowedModelsDialogProps> = ({
    isOpen,
    onClose,
    akCode,
    akName,
    parentAllowedModels,
    onSuccess,
}) => {
    const [currentModels, setCurrentModels] = useState<string[]>([])
    const [availableModels, setAvailableModels] = useState<string[]>([])
    const [isLoading, setIsLoading] = useState(false)
    const [isSaving, setIsSaving] = useState(false)
    const [error, setError] = useState('')
    const [showAddPanel, setShowAddPanel] = useState(false)
    const [showClearConfirm, setShowClearConfirm] = useState(false)
    const { toast } = useToast()

    const loadData = useCallback(async () => {
        if (!isOpen) return
        setIsLoading(true)
        setError('')
        try {
            // 并行拉取：当前白名单 + 平台所有可用模型
            const [models, platformModels] = await Promise.all([
                getAllowedModels(akCode),
                listConsoleModels('', '', '', 'active', '').catch(() => []),
            ])
            setCurrentModels(models)

            // 可选范围：有父 AK 白名单时仅显示父 AK 内的模型；否则显示平台所有模型
            const platformNames = platformModels.map((m) => m.modelName).filter(Boolean)
            if (parentAllowedModels && parentAllowedModels.length > 0) {
                setAvailableModels(parentAllowedModels)
            } else {
                setAvailableModels(platformNames.length > 0 ? platformNames : [])
            }
        } catch (e) {
            setError('加载数据失败，请重试')
        } finally {
            setIsLoading(false)
        }
    }, [isOpen, akCode, parentAllowedModels])

    useEffect(() => {
        loadData()
    }, [loadData])

    const handleClose = useCallback(() => {
        setShowAddPanel(false)
        setShowClearConfirm(false)
        setError('')
        onClose()
    }, [onClose])

    const handleRemove = useCallback(async (modelName: string) => {
        setIsSaving(true)
        setError('')
        try {
            await removeAllowedModels(akCode, [modelName])
            const next = currentModels.filter(m => m !== modelName)
            setCurrentModels(next)
            onSuccess?.(next)
            toast({ title: "已移除", description: `模型 ${modelName} 已从白名单移除` })
        } catch (e: unknown) {
            const msg = (e as { response?: { data?: { message?: string } } })?.response?.data?.message || '移除失败，请重试'
            setError(msg)
            toast({ title: "移除失败", description: msg, variant: "destructive" })
        } finally {
            setIsSaving(false)
        }
    }, [akCode, currentModels, onSuccess, toast])

    const handleAdd = useCallback(async (modelName: string) => {
        if (currentModels.includes(modelName)) return
        setIsSaving(true)
        setError('')
        try {
            await addAllowedModels(akCode, [modelName])
            const next = [...currentModels, modelName]
            setCurrentModels(next)
            onSuccess?.(next)
            toast({ title: "已添加", description: `模型 ${modelName} 已加入白名单` })
        } catch (e: unknown) {
            const msg = (e as { response?: { data?: { message?: string } } })?.response?.data?.message || '添加失败，请重试'
            setError(msg)
            toast({ title: "添加失败", description: msg, variant: "destructive" })
        } finally {
            setIsSaving(false)
        }
    }, [akCode, currentModels, onSuccess, toast])

    const handleClear = useCallback(async () => {
        setIsSaving(true)
        setError('')
        try {
            await replaceAllowedModels(akCode, [])
            setCurrentModels([])
            setShowClearConfirm(false)
            onSuccess?.([])
            toast({ title: "已清空", description: "白名单已清空，该 AK 现在可访问所有模型" })
        } catch (e: unknown) {
            const msg = (e as { response?: { data?: { message?: string } } })?.response?.data?.message || '清空失败，请重试'
            setError(msg)
            toast({ title: "清空失败", description: msg, variant: "destructive" })
        } finally {
            setIsSaving(false)
        }
    }, [akCode, onSuccess, toast])

    // 可以被添加的模型（从可用列表中去掉已经在白名单里的）
    const addableModels = availableModels.filter(m => !currentModels.includes(m))

    const hasWhitelist = currentModels.length > 0

    return (
        <Dialog open={isOpen} onOpenChange={handleClose}>
            <DialogContent className="max-w-lg max-h-[80vh] overflow-hidden flex flex-col bg-white border border-gray-200 shadow-lg">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        {hasWhitelist
                            ? <ShieldCheck className="h-5 w-5 text-amber-600" />
                            : <ShieldOff className="h-5 w-5 text-gray-400" />
                        }
                        模型白名单
                    </DialogTitle>
                    <DialogDescription>
                        {akName ? `${akName}（${akCode}）` : akCode}
                    </DialogDescription>
                </DialogHeader>

                <div className="flex-1 overflow-y-auto space-y-4 py-1">
                    {/* 状态说明 */}
                    {!isLoading && (
                        <div className={`px-3 py-2 rounded-md text-sm flex items-center gap-2 ${
                            hasWhitelist
                                ? 'bg-amber-50 text-amber-800 border border-amber-200'
                                : 'bg-gray-50 text-gray-600 border border-gray-200'
                        }`}>
                            {hasWhitelist
                                ? <>
                                    <ShieldCheck className="h-4 w-4 flex-shrink-0" />
                                    已限制：只能访问以下 {currentModels.length} 个模型
                                  </>
                                : <>
                                    <ShieldOff className="h-4 w-4 flex-shrink-0" />
                                    未限制：可访问所有模型
                                  </>
                            }
                        </div>
                    )}

                    {/* 加载中 */}
                    {isLoading && (
                        <div className="flex justify-center items-center py-8">
                            <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
                        </div>
                    )}

                    {/* 错误提示 */}
                    {error && (
                        <Alert variant="destructive">
                            <AlertCircle className="h-4 w-4" />
                            <AlertDescription>{error}</AlertDescription>
                        </Alert>
                    )}

                    {/* 当前白名单列表 */}
                    {!isLoading && hasWhitelist && (
                        <div className="space-y-2">
                            <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">当前白名单</p>
                            <div className="flex flex-wrap gap-2">
                                {currentModels.map(model => (
                                    <span
                                        key={model}
                                        className="inline-flex items-center gap-1 px-2 py-1 bg-gray-100 text-gray-800 rounded-md text-sm font-mono border border-gray-200"
                                    >
                                        {model}
                                        <button
                                            onClick={() => handleRemove(model)}
                                            disabled={isSaving}
                                            className="text-gray-400 hover:text-red-500 transition-colors disabled:opacity-50 ml-0.5"
                                            title={`移除 ${model}`}
                                        >
                                            <X className="h-3 w-3" />
                                        </button>
                                    </span>
                                ))}
                            </div>
                        </div>
                    )}

                    {/* 添加模型面板 */}
                    {!isLoading && showAddPanel && (
                        <div className="space-y-2">
                            <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">选择要添加的模型</p>
                            {addableModels.length === 0 ? (
                                <p className="text-sm text-gray-400 py-2">
                                    {availableModels.length === 0
                                        ? '暂无可用模型数据'
                                        : '所有可用模型均已在白名单中'}
                                </p>
                            ) : (
                                <div className="flex flex-wrap gap-2 max-h-48 overflow-y-auto">
                                    {addableModels.map(model => (
                                        <button
                                            key={model}
                                            onClick={() => handleAdd(model)}
                                            disabled={isSaving}
                                            className="inline-flex items-center gap-1 px-2 py-1 bg-white text-gray-700 rounded-md text-sm font-mono border border-gray-300 hover:border-gray-500 hover:bg-gray-50 transition-colors disabled:opacity-50"
                                        >
                                            <Plus className="h-3 w-3" />
                                            {model}
                                        </button>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}

                    {/* 清空确认 */}
                    {showClearConfirm && (
                        <div className="border border-red-200 rounded-md p-3 bg-red-50 space-y-2">
                            <div className="flex items-start gap-2 text-red-800 text-sm">
                                <TriangleAlert className="h-4 w-4 flex-shrink-0 mt-0.5" />
                                <span>清空后该 AK 将恢复为<strong>不限制模型</strong>，确认继续吗？</span>
                            </div>
                            <div className="flex gap-2">
                                <Button
                                    size="sm"
                                    variant="destructive"
                                    onClick={handleClear}
                                    disabled={isSaving}
                                >
                                    {isSaving ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null}
                                    确认清空
                                </Button>
                                <Button
                                    size="sm"
                                    variant="outline"
                                    onClick={() => setShowClearConfirm(false)}
                                    disabled={isSaving}
                                >
                                    取消
                                </Button>
                            </div>
                        </div>
                    )}
                </div>

                <DialogFooter className="flex-wrap gap-2 sm:justify-between">
                    <div className="flex gap-2">
                        {!isLoading && !showClearConfirm && (
                            <Button
                                size="sm"
                                variant="outline"
                                onClick={() => { setShowAddPanel(v => !v); setShowClearConfirm(false) }}
                                disabled={isSaving}
                                className="text-gray-700"
                            >
                                <Plus className="h-3.5 w-3.5 mr-1" />
                                {showAddPanel ? '收起' : '添加模型'}
                            </Button>
                        )}
                        {!isLoading && hasWhitelist && !showClearConfirm && (
                            <Button
                                size="sm"
                                variant="outline"
                                onClick={() => { setShowClearConfirm(true); setShowAddPanel(false) }}
                                disabled={isSaving}
                                className="text-red-600 border-red-200 hover:bg-red-50 hover:border-red-300"
                            >
                                清空白名单
                            </Button>
                        )}
                    </div>
                    <Button variant="outline" size="sm" onClick={handleClose} disabled={isSaving}>
                        关闭
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}