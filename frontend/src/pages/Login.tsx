import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuthStore } from "@/store/useAuthStore";
import { Loader2 } from "lucide-react";

export default function Login() {
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState("");
    const [loading, setLoading] = useState(false);

    const navigate = useNavigate();
    const setToken = useAuthStore((state) => state.setToken);

    const handleLogin = async (e: React.FormEvent) => {
        e.preventDefault();
        setError("");
        setLoading(true);

        try {
            // OAuth2 payload needs client_id, grant_type, username, password...
            // Axios URLSearchParams makes it x-www-form-urlencoded
            const params = new URLSearchParams();
            params.append("username", username);
            params.append("password", password);

            const { data } = await api.post("/auth/login", params);

            // We don't have /me endpoint yet, so we assume normal user for now.
            // Once we implement /me, we should fetch user data.
            setToken(data.access_token, false);
            navigate("/");
        } catch (err: any) {
            setError(err.response?.data?.detail || "登录失败，请检查用户名和密码");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="flex h-screen w-full items-center justify-center bg-zinc-950">
            <div className="w-full max-w-sm rounded-xl border border-zinc-800 bg-zinc-900 p-8 shadow-2xl">
                <div className="mb-8 text-center">
                    <h1 className="text-2xl font-bold tracking-tight text-white mb-2">
                        BinanceBot V3.0
                    </h1>
                    <p className="text-sm text-zinc-400">工业级量化管理平台</p>
                </div>

                {error && (
                    <div className="mb-4 rounded-md bg-red-500/10 p-3 text-sm text-red-500 border border-red-500/20">
                        {error}
                    </div>
                )}

                <form onSubmit={handleLogin} className="space-y-4">
                    <div className="space-y-2">
                        <label className="text-sm font-medium text-zinc-200">用户名</label>
                        <input
                            type="text"
                            required
                            className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-white placeholder:text-zinc-500 focus:border-zinc-500 focus:outline-none focus:ring-1 focus:ring-zinc-500"
                            placeholder="请输入用户名"
                            value={username}
                            onChange={(e) => setUsername(e.target.value)}
                        />
                    </div>
                    <div className="space-y-2">
                        <label className="text-sm font-medium text-zinc-200">密码</label>
                        <input
                            type="password"
                            required
                            className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-white placeholder:text-zinc-500 focus:border-zinc-500 focus:outline-none focus:ring-1 focus:ring-zinc-500"
                            placeholder="••••••••"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                        />
                    </div>

                    <button
                        type="submit"
                        disabled={loading}
                        className="w-full rounded-md bg-white px-4 py-2 text-sm font-medium text-zinc-950 transition-colors hover:bg-zinc-200 disabled:opacity-50 disabled:cursor-not-allowed flex justify-center items-center"
                    >
                        {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                        进入控制台
                    </button>
                </form>

                <div className="mt-6 text-center text-sm text-zinc-400">
                    还没有账号？{" "}
                    <Link to="/register" className="text-white hover:underline">
                        立即注册
                    </Link>
                </div>
            </div>
        </div>
    );
}
