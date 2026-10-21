"use client"

import { useState } from "react"
import { useForm } from "react-hook-form"
import { Loader2, Lock, Mail, Eye, EyeOff } from "lucide-react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { LoginAPI } from "@/api/Login/Login"
import { toast } from "sonner"
import Image from "next/image"
import { useRole } from "@/context/RoleContext"
import { useBranding } from "@/context/BrandingContext"

type FormData = {
  username: string
  password: string
}

interface UserResponse {
  username: string
  email: string
  role: "ADMIN" | "CHIEF_PRINCIPAL" | "PRINCIPAL" | "TEACHER" | "STAFF" | "ACCOUNTANT" | "FEE_MANAGER" | "STUDENT"
  id: number
}

interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  user: UserResponse
}

interface ApiErrorResponse {
  response?: {
    data?: {
      detail?: string
    }
  }
}

export default function LoginForm() {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormData>()
  const [isLoading, setIsLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false);
  const router = useRouter()
  const { setRole } = useRole()
  const { logoUrl } = useBranding()

  const onSubmit = async (data: FormData) => {
    setIsLoading(true)
    try {
      const response: LoginResponse = await LoginAPI(data)
      if (response?.user) {
        // Store auth token for axios interceptor and ProtectedRoute
        localStorage.setItem("authToken", response.access_token)
        // Store full user object to localStorage (persists across refresh)
        localStorage.setItem("user", JSON.stringify(response.user))
        // Also store to sessionStorage for current session
        sessionStorage.setItem("user", JSON.stringify(response.user))
        // Store the user's role for authorization checks
        sessionStorage.setItem("userRole", response.user.role)
        
        // Update RoleContext's React state directly so ProtectedRoute
        // sees the role immediately on navigation — without waiting for
        // RoleContext's useEffect to re-run (it won't, because RoleProvider
        // is already mounted in the root layout and persists across routes).
        setRole(response.user.role)
        
        toast.success("Login Successfully!")
        router.push("/dashboard")
      } else {
        toast.error("Invalid credentials, please try again.")
      }
    } catch (error: unknown) {
      const apiError = error as ApiErrorResponse
      toast.error(apiError.response?.data?.detail || "Login failed. Please try again.")
    } finally {
      setIsLoading(false)
    }
  }

  const togglePasswordVisibility = () => setShowPassword(!showPassword);

  return (
    <div className="flex min-h-screen items-center justify-center bg-[radial-gradient(circle_at_top_left,_rgba(59,130,246,0.16),_transparent_30%),linear-gradient(135deg,_#f8fbff_0%,_#eef4ff_100%)] p-4">
      <div className="w-full max-w-md rounded-[28px] border border-slate-200/80 bg-white/80 p-5 shadow-[0_30px_90px_-30px_rgba(15,23,42,0.45)] backdrop-blur-xl sm:p-8">
        <div className="flex justify-center">
          <div className="rounded-2xl bg-gradient-to-br from-slate-900 via-blue-900 to-slate-800 p-3 shadow-lg">
            <Image
                  src={logoUrl || "/logo.png"}
                  alt="logo"
                  width={96}
                  height={96}
                  className="rounded-full object-cover"
                  unoptimized
                />
          </div>
        </div>
        <h2 className="mt-6 text-center text-3xl font-semibold tracking-tight text-slate-900">Welcome back</h2>
        <p className="mb-6 mt-2 text-center text-sm text-slate-600">Enter your credentials to access your account</p>
        <form method="post" onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div>
            <label htmlFor="username" className="mb-1.5 block text-sm font-medium text-slate-700">Username</label>
            <div className="relative mt-1">
              <Mail className="pointer-events-none absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" />
              <input
                id="username"
                type="text"
                placeholder="Enter your username"
                className="w-full rounded-xl border border-slate-200 bg-white px-10 py-2.5 text-slate-900 shadow-sm outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                {...register("username", { required: "This field is required" })}
              />
            </div>
            {errors.username && <p className="mt-1 text-sm text-red-500">{errors.username.message}</p>}
          </div>

          <div>
            <label htmlFor="password" className="mb-1.5 block text-sm font-medium text-slate-700">Password</label>
            <div className="relative mt-1">
              <Lock className="pointer-events-none absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" />
              <input
                id="password"
                type={showPassword ? "text" : "password"}
                placeholder="Enter your password"
                className="w-full rounded-xl border border-slate-200 bg-white px-10 py-2.5 pr-12 text-slate-900 shadow-sm outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                {...register("password", { required: "Password is required" })}
              />
              <button
                type="button"
                aria-label={showPassword ? "Hide password" : "Show password"}
                onClick={togglePasswordVisibility}
                className="absolute right-3 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-md text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
              >
                {showPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
              </button>
            </div>
            {errors.password && <p className="mt-1 text-sm text-red-500">{errors.password.message}</p>}
          </div>

          <button
            type="submit"
            className="flex w-full items-center justify-center rounded-xl bg-gradient-to-r from-blue-600 to-cyan-500 py-2.5 font-medium text-white shadow-lg shadow-blue-200 transition hover:translate-y-[-1px] hover:shadow-blue-300 disabled:cursor-not-allowed disabled:opacity-70"
            disabled={isLoading}
          >
            {isLoading ? <Loader2 className="h-5 w-5 animate-spin" /> : "Sign In"}
          </button>
        </form>
        <div className="mt-5 text-center text-sm text-slate-600">
          <Link href="/student-login" className="font-medium text-blue-600 transition hover:text-blue-700">
            Student / Parent Login
          </Link>
        </div>
      </div>
    </div>
  )
}
