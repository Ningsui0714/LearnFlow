import { useNavigate } from 'react-router-dom'
import TutorPanel from '../components/tutor/TutorPanel'

export default function AgentPage() {
  const navigate = useNavigate()
  return (
    <div className="h-full overflow-hidden bg-gray-50 p-3 sm:p-5">
      <div className="mx-auto h-full max-w-5xl">
        <TutorPanel
          className="h-full"
          onProjectChange={project => project?.id && navigate(`/projects/${project.id}`)}
          onProposalAccepted={project => project?.id && navigate(`/projects/${project.id}`)}
        />
      </div>
    </div>
  )
}
