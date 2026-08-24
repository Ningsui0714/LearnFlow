import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import ProtectedRoute from './components/auth/ProtectedRoute'
import { useAuth } from './contexts/AuthContext'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import { getDesktopRuntime } from './services/desktopRuntime'


const Layout = lazy(() => import('./components/layout/Layout'))
const AgentPage = lazy(() => import('./pages/AgentPage'))
const CheckpointPage = lazy(() => import('./pages/CheckpointPage'))
const ExercisePage = lazy(() => import('./pages/ExercisePage'))
const HomePage = lazy(() => import('./pages/HomePage'))
const ReviewPage = lazy(() => import('./pages/ReviewPage'))
const ProfilePage = lazy(() => import('./pages/ProfilePage'))
const ProjectPage = lazy(() => import('./pages/ProjectPage'))
const LearningTasksPage = lazy(() => import('./pages/LearningTasksPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))
const DemoEntryPage = lazy(() => import('./pages/DemoEntryPage'))
const WorkspaceFilePage = lazy(() => import('./pages/WorkspaceFilePage'))
const LearningRunPage = lazy(() => import('./pages/LearningRunPage'))

function RouteLoading() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 text-slate-600">
      <div className="rounded-2xl border border-slate-200 bg-white px-5 py-4 text-sm shadow-sm" role="status" aria-live="polite">
        正在打开学习空间…
      </div>
    </main>
  )
}

function DevSettingsRoute() {
  const { user } = useAuth()
  return user?.is_dev_login || Boolean(getDesktopRuntime().apiBaseUrl) ? <SettingsPage /> : <Navigate to="/agent" replace />
}

export default function App() {
  return (
    <Suspense fallback={<RouteLoading />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/demo" element={<DemoEntryPage />} />
        <Route element={<ProtectedRoute />}>
          <Route element={<Layout />}>
            <Route path="/" element={<Navigate to="/agent" replace />} />
            <Route path="/agent" element={<AgentPage />} />
            <Route path="/agent/:sessionId" element={<AgentPage />} />
            <Route path="/learn/:runId" element={<LearningRunPage />} />
            <Route path="/projects" element={<HomePage />} />
            <Route path="/growth" element={<ProfilePage />} />
            <Route path="/profile" element={<Navigate to="/growth?section=profile" replace />} />
            <Route path="/memory" element={<Navigate to="/growth?section=memories" replace />} />
            <Route path="/review" element={<ReviewPage />} />
            <Route path="/tasks" element={<LearningTasksPage />} />
            <Route path="/settings" element={<DevSettingsRoute />} />
            <Route path="/projects/:projectId" element={<ProjectPage />} />
            <Route path="/projects/:projectId/checkpoints/:checkpointId" element={<CheckpointPage />} />
            <Route path="/projects/:projectId/checkpoints/:checkpointId/exercises" element={<ExercisePage />} />
            <Route path="/projects/:projectId/workspace" element={<WorkspaceFilePage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/agent" replace />} />
      </Routes>
    </Suspense>
  )
}
