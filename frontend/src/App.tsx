import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/layout/Layout'
import HomePage from './pages/HomePage'
import ProjectPage from './pages/ProjectPage'
import CheckpointPage from './pages/CheckpointPage'
import ExercisePage from './pages/ExercisePage'
import SettingsPage from './pages/SettingsPage'

function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/projects/:projectId" element={<ProjectPage />} />
        <Route path="/projects/:projectId/checkpoints/:checkpointId" element={<CheckpointPage />} />
        <Route path="/projects/:projectId/checkpoints/:checkpointId/exercises" element={<ExercisePage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}

export default App
