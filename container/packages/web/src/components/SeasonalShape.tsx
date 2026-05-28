import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'

interface Props {
  weekly?: number[]
  hourly?: number[]
  monthly?: number[]
}

const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const MONTH_LABELS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const HOUR_LABELS = Array.from({ length: 24 }, (_, i) => `${String(i).padStart(2, '0')}`)

function SeasonalChart({ data, title }: { data: { name: string; value: number }[]; title: string }) {
  return (
    <div>
      <h4 className="text-sm font-medium text-gray-700 mb-2">{title}</h4>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="name" tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} width={50} />
          <Tooltip />
          <Bar dataKey="value" fill="#6366f1" radius={[2, 2, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export default function SeasonalShape({ weekly, hourly, monthly }: Props) {
  const hasAny = weekly || hourly || monthly

  if (!hasAny) {
    return (
      <div className="bg-gray-50 rounded-lg p-6 text-center text-gray-400 text-sm">
        No seasonal data available
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {weekly && weekly.length === 7 && (
        <SeasonalChart
          title="Weekly Pattern"
          data={weekly.map((v, i) => ({ name: DAY_LABELS[i], value: v }))}
        />
      )}
      {monthly && monthly.length === 12 && (
        <SeasonalChart
          title="Monthly Pattern"
          data={monthly.map((v, i) => ({ name: MONTH_LABELS[i], value: v }))}
        />
      )}
      {hourly && hourly.length === 24 && (
        <SeasonalChart
          title="Hourly Pattern"
          data={hourly.map((v, i) => ({ name: HOUR_LABELS[i], value: v }))}
        />
      )}
    </div>
  )
}
