import React from 'react';

const STATUS_LABELS = {
  downloading: 'Downloading',
  completed: 'Completed',
  failed: 'Failed',
  queued: 'Queued',
  tagging: 'Tagging',
  cancelled: 'Cancelled',
  pending: 'Pending',
  processing: 'Processing',
};

export default function StatusBadge({ status }) {
  const normalized = (status || '').toLowerCase().replace(/[^a-z]/g, '');
  const label = STATUS_LABELS[normalized] || status || 'Unknown';

  let cls = 'badge';
  if (normalized === 'downloading') cls += ' badge-downloading';
  else if (normalized === 'completed' || normalized === 'done') cls += ' badge-completed';
  else if (normalized === 'failed' || normalized === 'error') cls += ' badge-failed';
  else if (normalized === 'tagging' || normalized === 'processing') cls += ' badge-tagging';
  else if (normalized === 'cancelled') cls += ' badge-cancelled';
  else cls += ' badge-queued';

  return <span className={cls}>{label}</span>;
}
