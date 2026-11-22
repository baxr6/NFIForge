// angles in degrees, 0 = 12 o'clock, clockwise positive; gauges are drawn in a 200x200 box around (100, 100)
export const C = 100

export function pt(angle: number, radius: number): [number, number] {
  const radians = (angle * Math.PI) / 180
  return [C + radius * Math.sin(radians), C - radius * Math.cos(radians)]
}

// thin arc along radius r
export function arcPath(fromAngle: number, toAngle: number, radius: number): string {
  const [x0, y0] = pt(fromAngle, radius)
  const [x1, y1] = pt(toAngle, radius)
  return `M ${x0} ${y0} A ${radius} ${radius} 0 ${toAngle - fromAngle > 180 ? 1 : 0} 1 ${x1} ${y1}`
}

// filled ring segment between radii r0 < r1
export function bandPath(fromAngle: number, toAngle: number, innerRadius: number, outerRadius: number): string {
  const [ax, ay] = pt(fromAngle, outerRadius)
  const [bx, by] = pt(toAngle, outerRadius)
  const [cx, cy] = pt(toAngle, innerRadius)
  const [dx, dy] = pt(fromAngle, innerRadius)
  const large = toAngle - fromAngle > 180 ? 1 : 0
  return `M ${ax} ${ay} A ${outerRadius} ${outerRadius} 0 ${large} 1 ${bx} ${by} L ${cx} ${cy} A ${innerRadius} ${innerRadius} 0 ${large} 0 ${dx} ${dy} Z`
}

export const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))

// unique svg ids so several gauges on one page don't share gradients
let seq = 0
export const uid = (prefix: string) => `${prefix}${++seq}`
