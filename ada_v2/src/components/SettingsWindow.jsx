import React, { useState, useEffect, useRef } from 'react';
import { X, Eye, EyeOff, CheckCircle, AlertCircle, Loader, ChevronDown, ChevronRight } from 'lucide-react';

const TOOLS = [
    { id: 'generate_cad', label: 'Generate CAD' },
    { id: 'run_web_agent', label: 'Web Agent' },
    { id: 'write_file', label: 'Write File' },
    { id: 'read_directory', label: 'Read Directory' },
    { id: 'read_file', label: 'Read File' },
    { id: 'create_project', label: 'Create Project' },
    { id: 'switch_project', label: 'Switch Project' },
    { id: 'list_projects', label: 'List Projects' },
    { id: 'list_smart_devices', label: 'List Devices' },
    { id: 'control_light', label: 'Control Light' },
    { id: 'discover_printers', label: 'Discover Printers' },
    { id: 'print_stl', label: 'Print 3D Model' },
    { id: 'iterate_cad', label: 'Iterate CAD' },
    { id: 'remember_fact', label: 'Remember Fact (Memory)' },
    { id: 'recall_memory', label: 'Recall Memory' },
    { id: 'self_improve', label: 'Self-Improvement' },
    { id: 'run_terminal', label: 'Run Terminal' },
    { id: 'run_python_code', label: 'Run Python Code' },
    { id: 'install_package', label: 'Install Package' },
];

const VOICE_OPTIONS = [
    { value: 'Aoede', label: 'Aoede (Female - Default)' },
    { value: 'Charon', label: 'Charon (Female)' },
    { value: 'Fenrir', label: 'Fenrir (Female)' },
    { value: 'Kore', label: 'Kore (Female)' },
    { value: 'Leda', label: 'Leda (Female)' },
    { value: 'Puck', label: 'Puck (Male)' },
    { value: 'Orus', label: 'Orus (Male)' },
    { value: 'Zephyr', label: 'Zephyr (Male)' },
];

const ENGINE_OPTIONS = [
    { value: 'auto', label: 'Auto (try all in order)' },
    { value: 'local', label: 'Local Only (MLX / Ollama)' },
    { value: 'gemini', label: 'Gemini Only' },
    { value: 'cloud', label: 'Cloud Only (Gemini + OpenRouter)' },
];

const CollapsibleSection = ({ title, defaultOpen = false, children }) => {
    const [open, setOpen] = useState(defaultOpen);
    return (
        <div className="mb-3 border border-green-900/30 rounded-lg overflow-hidden">
            <button
                onClick={() => setOpen(!open)}
                className="w-full flex items-center gap-2 px-3 py-2 bg-gray-900/50 hover:bg-gray-900/80 transition-colors text-left"
            >
                {open ? <ChevronDown size={12} className="text-green-500" /> : <ChevronRight size={12} className="text-green-500" />}
                <span className="text-xs font-bold uppercase tracking-wider text-green-400">{title}</span>
            </button>
            {open && <div className="px-3 py-3 space-y-3 bg-black/20">{children}</div>}
        </div>
    );
};

const ApiKeyInput = ({ label, value, onChange, placeholder, isSet, onTest, onClear, testing, testResult }) => {
    const [visible, setVisible] = useState(false);
    return (
        <div className="space-y-1.5">
            <div className="flex items-center justify-between">
                <span className="text-[11px] text-green-100/80 font-mono">{label}</span>
                {isSet ? (
                    <span className="flex items-center gap-1 text-[10px] text-green-400"><CheckCircle size={10} /> Set</span>
                ) : (
                    <span className="flex items-center gap-1 text-[10px] text-yellow-500"><AlertCircle size={10} /> Not set</span>
                )}
            </div>
            <div className="relative">
                <input
                    type={visible ? 'text' : 'password'}
                    value={value}
                    onChange={e => onChange(e.target.value)}
                    placeholder={isSet ? '•••••••• (enter new to replace)' : placeholder}
                    className="w-full bg-gray-900 border border-green-800 rounded px-2.5 py-1.5 text-[11px] text-green-100 focus:border-green-400 outline-none pr-8 font-mono transition-colors"
                />
                <button
                    onMouseDown={e => { e.preventDefault(); setVisible(v => !v); }}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-green-700 hover:text-green-400"
                >
                    {visible ? <EyeOff size={11} /> : <Eye size={11} />}
                </button>
            </div>
            <div className="flex gap-1.5">
                <button
                    onClick={() => onTest()}
                    disabled={!value.trim() || testing}
                    className={`flex-1 py-1 rounded text-[10px] font-semibold transition-all ${
                        value.trim() && !testing
                            ? 'bg-green-500/20 hover:bg-green-500/40 text-green-300 border border-green-500/50'
                            : 'bg-gray-900/40 text-green-900 border border-green-900/30 cursor-not-allowed'
                    }`}
                >
                    {testing ? <Loader size={10} className="animate-spin inline" /> : 'Test'}
                </button>
                {isSet && (
                    <button
                        onClick={onClear}
                        className="px-3 py-1 bg-red-900/20 hover:bg-red-900/50 text-red-400 border border-red-900/40 rounded text-[10px] transition-all"
                    >Clear</button>
                )}
            </div>
            {testResult && (
                <div className={`text-[10px] px-2 py-1 rounded ${testResult.ok ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'}`}>
                    {testResult.message}
                </div>
            )}
        </div>
    );
};

const SettingsWindow = ({
    socket,
    micDevices,
    speakerDevices,
    webcamDevices,
    selectedMicId,
    setSelectedMicId,
    selectedSpeakerId,
    setSelectedSpeakerId,
    selectedWebcamId,
    setSelectedWebcamId,
    cursorSensitivity,
    setCursorSensitivity,
    isCameraFlipped,
    setIsCameraFlipped,
    handleFileUpload,
    onClose
}) => {
    const [permissions, setPermissions] = useState({});
    const [faceAuthEnabled, setFaceAuthEnabled] = useState(false);
    const [selectedVoice, setSelectedVoice] = useState('Aoede');
    const [preferredEngine, setPreferredEngine] = useState('auto');
    const [ollamaModel, setOllamaModel] = useState('auto');
    const [localModelPath, setLocalModelPath] = useState('');

    const [geminiKey, setGeminiKey] = useState('');
    const [geminiKeySet, setGeminiKeySet] = useState(false);
    const [geminiTesting, setGeminiTesting] = useState(false);
    const [geminiTestResult, setGeminiTestResult] = useState(null);

    const [openrouterKey, setOpenrouterKey] = useState('');
    const [openrouterKeySet, setOpenrouterKeySet] = useState(false);
    const [openrouterTesting, setOpenrouterTesting] = useState(false);
    const [openrouterTestResult, setOpenrouterTestResult] = useState(null);

    const [nvidiaKey, setNvidiaKey] = useState('');
    const [nvidiaKeySet, setNvidiaKeySet] = useState(false);
    const [nvidiaTesting, setNvidiaTesting] = useState(false);
    const [nvidiaTestResult, setNvidiaTestResult] = useState(null);

    const [ollamaStatus, setOllamaStatus] = useState('unknown');
    const [selfImproveEnabled, setSelfImproveEnabled] = useState(true);
    const [selfImproveAuditN, setSelfImproveAuditN] = useState(20);
    const [selfImproveAutoApply, setSelfImproveAutoApply] = useState(false);

    useEffect(() => {
        socket.emit('get_settings');

        const handleSettings = (settings) => {
            if (!settings) return;
            if (settings.tool_permissions) setPermissions(settings.tool_permissions);
            if (typeof settings.face_auth_enabled !== 'undefined') setFaceAuthEnabled(settings.face_auth_enabled);
            if (settings.voice) setSelectedVoice(settings.voice);
            if (settings.preferred_engine) setPreferredEngine(settings.preferred_engine);
            if (settings.ollama_model) setOllamaModel(settings.ollama_model);
            if (settings.local_model_path !== undefined) setLocalModelPath(settings.local_model_path);

            if (settings.gemini_api_key === '••••') {
                setGeminiKeySet(true);
                setGeminiKey('');
            } else if (settings.gemini_api_key) {
                setGeminiKeySet(true);
                setGeminiKey('');
            } else {
                setGeminiKeySet(false);
                setGeminiKey('');
            }

            if (settings.openrouter_api_key === '••••') {
                setOpenrouterKeySet(true);
                setOpenrouterKey('');
            } else if (settings.openrouter_api_key) {
                setOpenrouterKeySet(true);
                setOpenrouterKey('');
            } else {
                setOpenrouterKeySet(false);
                setOpenrouterKey('');
            }

            if (settings.nvidia_api_key === '••••') {
                setNvidiaKeySet(true);
                setNvidiaKey('');
            } else if (settings.nvidia_api_key) {
                setNvidiaKeySet(true);
                setNvidiaKey('');
            } else {
                setNvidiaKeySet(false);
                setNvidiaKey('');
            }

            if (settings.self_improvement) {
                setSelfImproveEnabled(settings.self_improvement.enabled ?? true);
                setSelfImproveAuditN(settings.self_improvement.audit_every_n || 20);
                setSelfImproveAutoApply(settings.self_improvement.auto_apply_patches ?? false);
            }
        };

        const handleTestResult = (data) => {
            const { provider, ok, message } = data;
            const result = { ok, message };
            if (provider === 'gemini') { setGeminiTesting(false); setGeminiTestResult(result); }
            if (provider === 'openrouter') { setOpenrouterTesting(false); setOpenrouterTestResult(result); }
            if (provider === 'nvidia') { setNvidiaTesting(false); setNvidiaTestResult(result); }
        };

        socket.on('settings', handleSettings);
        socket.on('api_key_test_result', handleTestResult);
        return () => {
            socket.off('settings', handleSettings);
            socket.off('api_key_test_result', handleTestResult);
        };
    }, [socket]);

    useEffect(() => {
        const checkOllama = async () => {
            try {
                const res = await fetch('http://localhost:11434/api/tags', { signal: AbortSignal.timeout(2000) });
                setOllamaStatus(res.ok ? 'running' : 'offline');
            } catch { setOllamaStatus('offline'); }
        };
        checkOllama();
    }, []);

    const togglePermission = (toolId) => {
        const nextVal = !(permissions[toolId] !== false);
        socket.emit('update_settings', { tool_permissions: { [toolId]: nextVal } });
    };

    const toggleFaceAuth = () => {
        const newVal = !faceAuthEnabled;
        setFaceAuthEnabled(newVal);
        socket.emit('update_settings', { face_auth_enabled: newVal });
    };

    const toggleCameraFlip = () => {
        const newVal = !isCameraFlipped;
        setIsCameraFlipped(newVal);
        socket.emit('update_settings', { camera_flipped: newVal });
    };

    const saveGeminiKey = () => {
        if (!geminiKey.trim()) return;
        socket.emit('update_settings', { gemini_api_key: geminiKey.trim() });
        setGeminiKeySet(true);
    };

    const saveOpenrouterKey = () => {
        if (!openrouterKey.trim()) return;
        socket.emit('update_settings', { openrouter_api_key: openrouterKey.trim() });
        setOpenrouterKeySet(true);
    };

    const saveNvidiaKey = () => {
        if (!nvidiaKey.trim()) return;
        socket.emit('update_settings', { nvidia_api_key: nvidiaKey.trim() });
        setNvidiaKeySet(true);
    };

    const testApiKey = (provider, key) => {
        if (provider === 'gemini') setGeminiTesting(true);
        if (provider === 'openrouter') setOpenrouterTesting(true);
        if (provider === 'nvidia') setNvidiaTesting(true);
        socket.emit('test_api_key', { provider, key });
    };

    const clearApiKey = (provider) => {
        socket.emit('update_settings', { [`${provider}_api_key`]: '' });
        if (provider === 'gemini') { setGeminiKeySet(false); setGeminiKey(''); setGeminiTestResult(null); }
        if (provider === 'openrouter') { setOpenrouterKeySet(false); setOpenrouterKey(''); setOpenrouterTestResult(null); }
        if (provider === 'nvidia') { setNvidiaKeySet(false); setNvidiaKey(''); setNvidiaTestResult(null); }
    };

    return (
        <div className="overflow-y-auto max-h-[calc(100vh-120px)] pr-2 absolute top-20 right-10 bg-black/90 border border-green-500/50 p-4 rounded-lg z-50 w-96 backdrop-blur-xl shadow-[0_0_30px_rgba(74,222,128,0.2)]" style={{ scrollbarWidth: 'thin', scrollbarColor: '#166534 #111' }}>
            <div className="flex justify-between items-center mb-3 border-b border-green-900/50 pb-2">
                <h2 className="text-green-400 font-bold text-sm uppercase tracking-wider">Settings</h2>
                <button onClick={onClose} className="text-green-600 hover:text-green-400"><X size={16} /></button>
            </div>

            {/* AI & Models */}
            <CollapsibleSection title="AI & Models" defaultOpen={true}>
                <div className="space-y-1.5">
                    <label className="text-[11px] text-green-100/80">Preferred Engine</label>
                    <select
                        value={preferredEngine}
                        onChange={e => { setPreferredEngine(e.target.value); socket.emit('update_settings', { preferred_engine: e.target.value }); }}
                        className="w-full bg-gray-900 border border-green-800 rounded p-1.5 text-[11px] text-green-100 focus:border-green-400 outline-none"
                    >
                        {ENGINE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                    </select>
                </div>

                <ApiKeyInput
                    label="Gemini API Key"
                    value={geminiKey}
                    onChange={setGeminiKey}
                    placeholder="Paste your Gemini API key..."
                    isSet={geminiKeySet}
                    onTest={() => testApiKey('gemini', geminiKey)}
                    onClear={() => clearApiKey('gemini')}
                    testing={geminiTesting}
                    testResult={geminiTestResult}
                />
                <button onClick={saveGeminiKey} disabled={!geminiKey.trim()}
                    className={`w-full py-1.5 rounded text-[11px] font-semibold transition-all ${geminiKey.trim() ? 'bg-green-500/20 hover:bg-green-500/40 text-green-300 border border-green-500/50' : 'bg-gray-900/40 text-green-900 border border-green-900/30 cursor-not-allowed'}`}
                >Save Gemini Key</button>

                <ApiKeyInput
                    label="OpenRouter API Key"
                    value={openrouterKey}
                    onChange={setOpenrouterKey}
                    placeholder="Optional - cloud fallback..."
                    isSet={openrouterKeySet}
                    onTest={() => testApiKey('openrouter', openrouterKey)}
                    onClear={() => clearApiKey('openrouter')}
                    testing={openrouterTesting}
                    testResult={openrouterTestResult}
                />
                <button onClick={saveOpenrouterKey} disabled={!openrouterKey.trim()}
                    className={`w-full py-1.5 rounded text-[11px] font-semibold transition-all ${openrouterKey.trim() ? 'bg-green-500/20 hover:bg-green-500/40 text-green-300 border border-green-500/50' : 'bg-gray-900/40 text-green-900 border border-green-900/30 cursor-not-allowed'}`}
                >Save OpenRouter Key</button>

                <ApiKeyInput
                    label="NVIDIA API Key"
                    value={nvidiaKey}
                    onChange={setNvidiaKey}
                    placeholder="Optional - for self-improvement..."
                    isSet={nvidiaKeySet}
                    onTest={() => testApiKey('nvidia', nvidiaKey)}
                    onClear={() => clearApiKey('nvidia')}
                    testing={nvidiaTesting}
                    testResult={nvidiaTestResult}
                />
                <button onClick={saveNvidiaKey} disabled={!nvidiaKey.trim()}
                    className={`w-full py-1.5 rounded text-[11px] font-semibold transition-all ${nvidiaKey.trim() ? 'bg-green-500/20 hover:bg-green-500/40 text-green-300 border border-green-500/50' : 'bg-gray-900/40 text-green-900 border border-green-900/30 cursor-not-allowed'}`}
                >Save NVIDIA Key</button>

                <div className="space-y-1.5">
                    <label className="text-[11px] text-green-100/80">Local Model Path (optional)</label>
                    <input
                        type="text"
                        value={localModelPath}
                        onChange={e => setLocalModelPath(e.target.value)}
                        onBlur={() => socket.emit('update_settings', { local_model_path: localModelPath })}
                        placeholder="/path/to/local/model"
                        className="w-full bg-gray-900 border border-green-800 rounded px-2.5 py-1.5 text-[11px] text-green-100 focus:border-green-400 outline-none font-mono"
                    />
                </div>

                <div className="space-y-1.5">
                    <div className="flex items-center justify-between">
                        <label className="text-[11px] text-green-100/80">Ollama Model</label>
                        {ollamaStatus === 'running' && <span className="flex items-center gap-1 text-[10px] text-green-400"><span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse inline-block" /> Running</span>}
                        {ollamaStatus === 'offline' && <span className="flex items-center gap-1 text-[10px] text-yellow-500"><span className="w-1.5 h-1.5 rounded-full bg-yellow-500 inline-block" /> Offline</span>}
                    </div>
                    <select
                        value={ollamaModel}
                        onChange={e => { setOllamaModel(e.target.value); socket.emit('update_settings', { ollama_model: e.target.value }); }}
                        className="w-full bg-gray-900 border border-green-800 rounded p-1.5 text-[11px] text-green-100 focus:border-green-400 outline-none"
                    >
                        <option value="auto">Auto (detect best)</option>
                        <option value="qwen2.5:14b">Qwen 2.5 14B</option>
                        <option value="qwen2.5:7b">Qwen 2.5 7B</option>
                        <option value="qwen2.5:3b">Qwen 2.5 3B</option>
                        <option value="qwen2.5-coder:14b">Qwen 2.5 Coder 14B</option>
                        <option value="qwen2.5-coder:7b">Qwen 2.5 Coder 7B</option>
                        <option value="qwen2.5-coder:3b">Qwen 2.5 Coder 3B</option>
                    </select>
                    <p className="text-[9px] text-green-800/60">Activates automatically when cloud quota is exhausted.</p>
                </div>

                <div className="space-y-1.5">
                    <label className="text-[11px] text-green-100/80">Voice</label>
                    <select
                        value={selectedVoice}
                        onChange={e => { setSelectedVoice(e.target.value); socket.emit('update_settings', { voice: e.target.value }); }}
                        className="w-full bg-gray-900 border border-green-800 rounded p-1.5 text-[11px] text-green-100 focus:border-green-400 outline-none"
                    >
                        {VOICE_OPTIONS.map(v => <option key={v.value} value={v.value}>{v.label}</option>)}
                    </select>
                    <p className="text-[9px] text-green-800/60">Restart JARVIS to apply voice change.</p>
                </div>
            </CollapsibleSection>

            {/* Capabilities */}
            <CollapsibleSection title="Capabilities">
                <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1" style={{ scrollbarWidth: 'thin', scrollbarColor: '#166534 #111' }}>
                    {TOOLS.map(tool => {
                        const isEnabled = permissions[tool.id] !== false;
                        return (
                            <div key={tool.id} className="flex items-center justify-between text-[11px] bg-gray-900/50 p-1.5 rounded border border-green-900/30">
                                <span className="text-green-100/80">{tool.label}</span>
                                <button
                                    onClick={() => togglePermission(tool.id)}
                                    className={`relative w-8 h-4 rounded-full transition-colors duration-200 ${isEnabled ? 'bg-green-500/80' : 'bg-gray-700'}`}
                                >
                                    <div className={`absolute top-0.5 left-0.5 w-3 h-3 bg-white rounded-full transition-transform duration-200 ${isEnabled ? 'translate-x-4' : 'translate-x-0'}`} />
                                </button>
                            </div>
                        );
                    })}
                </div>
            </CollapsibleSection>

            {/* Hardware */}
            <CollapsibleSection title="Hardware">
                <div className="space-y-2">
                    <div className="flex items-center justify-between text-[11px] bg-gray-900/50 p-2 rounded border border-green-900/30">
                        <span className="text-green-100/80">Face Authentication</span>
                        <button onClick={toggleFaceAuth}
                            className={`relative w-8 h-4 rounded-full transition-colors duration-200 ${faceAuthEnabled ? 'bg-green-500/80' : 'bg-gray-700'}`}
                        >
                            <div className={`absolute top-0.5 left-0.5 w-3 h-3 bg-white rounded-full transition-transform duration-200 ${faceAuthEnabled ? 'translate-x-4' : 'translate-x-0'}`} />
                        </button>
                    </div>
                    <div className="flex items-center justify-between text-[11px] bg-gray-900/50 p-2 rounded border border-green-900/30">
                        <span className="text-green-100/80">Flip Camera Horizontal</span>
                        <button onClick={toggleCameraFlip}
                            className={`relative w-8 h-4 rounded-full transition-colors duration-200 ${isCameraFlipped ? 'bg-green-500/80' : 'bg-gray-700'}`}
                        >
                            <div className={`absolute top-0.5 left-0.5 w-3 h-3 bg-white rounded-full transition-transform duration-200 ${isCameraFlipped ? 'translate-x-4' : 'translate-x-0'}`} />
                        </button>
                    </div>
                </div>

                <div className="space-y-1.5">
                    <label className="text-[11px] text-green-100/80">Microphone</label>
                    <select value={selectedMicId} onChange={e => setSelectedMicId(e.target.value)}
                        className="w-full bg-gray-900 border border-green-800 rounded p-1.5 text-[11px] text-green-100 focus:border-green-400 outline-none">
                        {micDevices.map((d, i) => <option key={d.deviceId} value={d.deviceId}>{d.label || `Mic ${i + 1}`}</option>)}
                    </select>
                </div>
                <div className="space-y-1.5">
                    <label className="text-[11px] text-green-100/80">Speaker</label>
                    <select value={selectedSpeakerId} onChange={e => setSelectedSpeakerId(e.target.value)}
                        className="w-full bg-gray-900 border border-green-800 rounded p-1.5 text-[11px] text-green-100 focus:border-green-400 outline-none">
                        {speakerDevices.map((d, i) => <option key={d.deviceId} value={d.deviceId}>{d.label || `Speaker ${i + 1}`}</option>)}
                    </select>
                </div>
                <div className="space-y-1.5">
                    <label className="text-[11px] text-green-100/80">Webcam</label>
                    <select value={selectedWebcamId} onChange={e => setSelectedWebcamId(e.target.value)}
                        className="w-full bg-gray-900 border border-green-800 rounded p-1.5 text-[11px] text-green-100 focus:border-green-400 outline-none">
                        {webcamDevices.map((d, i) => <option key={d.deviceId} value={d.deviceId}>{d.label || `Camera ${i + 1}`}</option>)}
                    </select>
                </div>
                <div className="space-y-1.5">
                    <div className="flex justify-between">
                        <label className="text-[11px] text-green-100/80">Cursor Sensitivity</label>
                        <span className="text-[10px] text-green-500">{cursorSensitivity}x</span>
                    </div>
                    <input type="range" min="1.0" max="5.0" step="0.1" value={cursorSensitivity}
                        onChange={e => {
                            const val = parseFloat(e.target.value);
                            setCursorSensitivity(val);
                            socket.emit('update_settings', { cursor_sensitivity: val });
                        }}
                        className="w-full accent-green-400 cursor-pointer h-1 bg-gray-800 rounded-lg appearance-none" />
                </div>
            </CollapsibleSection>

            {/* Self-Improvement */}
            <CollapsibleSection title="Self-Improvement">
                <div className="space-y-2">
                    <div className="flex items-center justify-between text-[11px] bg-gray-900/50 p-2 rounded border border-green-900/30">
                        <span className="text-green-100/80">Enabled</span>
                        <button onClick={() => { const v = !selfImproveEnabled; setSelfImproveEnabled(v); socket.emit('update_settings', { self_improvement: { enabled: v } }); }}
                            className={`relative w-8 h-4 rounded-full transition-colors duration-200 ${selfImproveEnabled ? 'bg-green-500/80' : 'bg-gray-700'}`}
                        >
                            <div className={`absolute top-0.5 left-0.5 w-3 h-3 bg-white rounded-full transition-transform duration-200 ${selfImproveEnabled ? 'translate-x-4' : 'translate-x-0'}`} />
                        </button>
                    </div>
                    <div className="space-y-1">
                        <div className="flex justify-between">
                            <label className="text-[11px] text-green-100/80">Audit every N interactions</label>
                            <span className="text-[10px] text-green-500">{selfImproveAuditN}</span>
                        </div>
                        <input type="range" min="10" max="50" step="5" value={selfImproveAuditN}
                            onChange={e => setSelfImproveAuditN(parseInt(e.target.value))}
                            onMouseUp={() => socket.emit('update_settings', { self_improvement: { audit_every_n: selfImproveAuditN } })}
                            className="w-full accent-green-400 cursor-pointer h-1 bg-gray-800 rounded-lg appearance-none" />
                    </div>
                    <div className="flex items-center justify-between text-[11px] bg-gray-900/50 p-2 rounded border border-green-900/30">
                        <span className="text-green-100/80">Auto-apply patches</span>
                        <button onClick={() => { const v = !selfImproveAutoApply; setSelfImproveAutoApply(v); socket.emit('update_settings', { self_improvement: { auto_apply_patches: v } }); }}
                            className={`relative w-8 h-4 rounded-full transition-colors duration-200 ${selfImproveAutoApply ? 'bg-green-500/80' : 'bg-gray-700'}`}
                        >
                            <div className={`absolute top-0.5 left-0.5 w-3 h-3 bg-white rounded-full transition-transform duration-200 ${selfImproveAutoApply ? 'translate-x-4' : 'translate-x-0'}`} />
                        </button>
                    </div>
                </div>
            </CollapsibleSection>

            {/* Memory */}
            <CollapsibleSection title="Memory">
                <div className="space-y-1.5">
                    <label className="text-[10px] text-green-500/60 uppercase">Upload Memory Text</label>
                    <input type="file" accept=".txt" onChange={handleFileUpload}
                        className="text-[11px] text-green-100 bg-gray-900 border border-green-800 rounded p-2 file:mr-2 file:py-1 file:px-2 file:rounded-full file:border-0 file:text-[10px] file:font-semibold file:bg-green-900 file:text-green-400 hover:file:bg-green-800 cursor-pointer" />
                </div>
            </CollapsibleSection>
        </div>
    );
};

export default SettingsWindow;
