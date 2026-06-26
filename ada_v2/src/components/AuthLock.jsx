import React, { useEffect, useState, useRef } from 'react';
import { Lock, Unlock, User, Camera, CameraOff, AlertTriangle } from 'lucide-react';

const AuthLock = ({ socket, onAuthenticated, onAnimationComplete }) => {
    const [frameSrc, setFrameSrc] = useState(null);
    const [message, setMessage] = useState("Initializing biometric scan...");
    const [isUnlocking, setIsUnlocking] = useState(false);
    const [cameraError, setCameraError] = useState(false);
    const [enrollMode, setEnrollMode] = useState(false);

    // If no frame arrives in 5s, assume camera failed
    const frameTimeoutRef = useRef(null);

    useEffect(() => {
        if (!socket) return;

        // Start a timer — if backend sends no frames in 5s, show error
        frameTimeoutRef.current = setTimeout(() => {
            if (!frameSrc && !isUnlocking) {
                setCameraError(true);
                setMessage("Camera not detected or face not enrolled.");
            }
        }, 5000);

        const handleAuthStatus = (data) => {
            if (data.authenticated && !isUnlocking) {
                clearTimeout(frameTimeoutRef.current);
                setIsUnlocking(true);
                setCameraError(false);
                setMessage("Identity Verified. Access Granted.");
                setTimeout(() => {
                    onAuthenticated(true);
                }, 2000);
            } else if (!data.authenticated && !isUnlocking) {
                setMessage("Look directly at the camera to unlock.");
            }
        };

        const handleAuthFrame = (data) => {
            clearTimeout(frameTimeoutRef.current);
            setCameraError(false);
            setFrameSrc(`data:image/jpeg;base64,${data.image}`);
        };

        socket.on('auth_status', handleAuthStatus);
        socket.on('auth_frame', handleAuthFrame);

        return () => {
            clearTimeout(frameTimeoutRef.current);
            socket.off('auth_status', handleAuthStatus);
            socket.off('auth_frame', handleAuthFrame);
        };
    }, [socket, onAuthenticated, isUnlocking, frameSrc]);

    // Enroll: capture current webcam frame and send as reference
    const handleEnroll = async () => {
        setEnrollMode(true);
        setMessage("Opening camera for enrollment...");
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ video: true });
            const video = document.createElement('video');
            video.srcObject = stream;
            await video.play();
            // Wait 1 frame
            await new Promise(r => setTimeout(r, 800));
            const canvas = document.createElement('canvas');
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            canvas.getContext('2d').drawImage(video, 0, 0);
            stream.getTracks().forEach(t => t.stop());
            const dataUrl = canvas.toDataURL('image/jpeg', 0.92);
            const base64 = dataUrl.split(',')[1];
            socket.emit('enroll_face', { image: base64 });
            setMessage("Face captured! Enrolling...");
        } catch (err) {
            setMessage(`Camera access denied: ${err.message}`);
            setEnrollMode(false);
        }
    };

    // Bypass: disable face auth and proceed
    const handleBypass = () => {
        socket.emit('update_settings', { face_auth_enabled: false });
        onAuthenticated(true);
    };

    return (
        <div
            className={`fixed inset-0 z-[9999] bg-black flex flex-col items-center justify-center font-mono select-none transition-all duration-[2000ms] ${isUnlocking ? 'opacity-0 scale-110 pointer-events-none' : 'opacity-100'}`}
            style={{ transitionDelay: isUnlocking ? '2000ms' : '0ms' }}
        >
            {/* Background */}
            <div className={`absolute inset-0 bg-[radial-gradient(circle_at_center,_var(--tw-gradient-stops))] ${isUnlocking ? 'from-green-900/40 via-black to-black' : 'from-green-900/20 via-black to-black'} pointer-events-none transition-colors duration-[1500ms]`} />

            <div className={`relative flex flex-col items-center gap-5 p-10 border ${isUnlocking ? 'border-green-500/60' : 'border-green-500/30'} rounded-lg bg-black/80 backdrop-blur-xl shadow-[0_0_50px_rgba(74,222,128,0.2)] transition-all duration-[1500ms] max-w-sm w-full mx-4`}>

                {/* Title */}
                <div className={`text-2xl font-bold tracking-[0.3em] uppercase drop-shadow-[0_0_10px_currentColor] flex items-center gap-3 ${isUnlocking ? 'text-green-400' : cameraError ? 'text-yellow-500' : 'text-green-500'} transition-colors duration-1000`}>
                    {isUnlocking ? <Unlock size={28} /> : cameraError ? <AlertTriangle size={28} /> : <Lock size={28} />}
                    {isUnlocking ? "SYSTEM UNLOCKED" : cameraError ? "ENROLL REQUIRED" : "SYSTEM LOCKED"}
                </div>

                {/* Camera Feed or Error State */}
                <div className={`relative w-56 h-56 border-2 ${isUnlocking ? 'border-green-500' : cameraError ? 'border-yellow-500/50' : 'border-green-500/50'} rounded-lg overflow-hidden bg-gray-950 shadow-inner flex items-center justify-center transition-all duration-500`}>
                    {frameSrc && !cameraError ? (
                        <img
                            src={frameSrc}
                            alt="Auth Camera"
                            className={`w-full h-full object-cover scale-x-[-1] transition-opacity duration-500 ${isUnlocking ? 'opacity-50 grayscale' : 'opacity-100'}`}
                        />
                    ) : cameraError ? (
                        <div className="flex flex-col items-center gap-2 text-yellow-600 p-4 text-center">
                            <CameraOff size={48} className="opacity-60" />
                            <p className="text-[10px] text-yellow-600/70 leading-tight">
                                No face enrolled or camera unavailable.
                            </p>
                        </div>
                    ) : (
                        <div className="animate-pulse text-green-800">
                            <User size={64} />
                        </div>
                    )}

                    {/* Scan line — only when camera is active and not unlocking */}
                    {frameSrc && !cameraError && !isUnlocking && (
                        <div className="absolute top-0 left-0 w-full h-0.5 bg-green-400/80 shadow-[0_0_15px_rgba(74,222,128,0.8)] animate-[scan_2s_ease-in-out_infinite]" />
                    )}

                    {/* Unlock overlay */}
                    {isUnlocking && (
                        <div className="absolute inset-0 flex items-center justify-center bg-green-500/20 animate-pulse">
                            <Unlock size={56} className="text-green-400 drop-shadow-[0_0_20px_rgba(74,222,128,0.8)]" />
                        </div>
                    )}
                </div>

                {/* Status Message */}
                <p className={`text-xs tracking-widest text-center animate-pulse ${cameraError ? 'text-yellow-400' : 'text-green-300'} transition-colors duration-500`}>
                    {message}
                </p>

                {/* Action Buttons — only shown on error/no camera */}
                {cameraError && !isUnlocking && (
                    <div className="flex flex-col gap-2 w-full">
                        <button
                            onClick={handleEnroll}
                            disabled={enrollMode}
                            className="flex items-center justify-center gap-2 w-full py-2 bg-green-500/15 hover:bg-green-500/30 text-green-300 border border-green-500/40 rounded text-xs font-semibold tracking-wider transition-all"
                        >
                            <Camera size={13} />
                            {enrollMode ? 'Capturing...' : 'Enroll My Face Now'}
                        </button>
                        <button
                            onClick={handleBypass}
                            className="w-full py-1.5 text-green-800 hover:text-green-600 text-[10px] tracking-wider transition-colors"
                        >
                            Disable face auth & continue →
                        </button>
                    </div>
                )}
            </div>

            <style>{`
                @keyframes scan {
                    0%   { top: 0%;   opacity: 0; }
                    10%  { opacity: 1; }
                    90%  { opacity: 1; }
                    100% { top: 100%; opacity: 0; }
                }
            `}</style>
        </div>
    );
};

export default AuthLock;
