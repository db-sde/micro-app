import React from 'react';

export default function DynamicFormRenderer({ data, onChange }) {
  if (!data || typeof data !== 'object') {
    return <div style={{ padding: '20px', color: '#64748B' }}>Invalid data format for form rendering.</div>;
  }

  const handleChange = (key, val) => {
    onChange({ ...data, [key]: val });
  };

  const renderField = (key, value) => {
    // Array of Objects / Tables
    if (Array.isArray(value)) {
      return (
        <div key={key} style={{ marginBottom: '24px', border: '1px solid #E2E8F0', padding: '16px', borderRadius: '8px', background: '#F8FAFC' }}>
          <h4 style={{ margin: '0 0 12px 0', fontSize: '14px', color: '#0F172A', textTransform: 'capitalize' }}>
            {key.replace(/_/g, ' ')} <span style={{ fontSize: '12px', color: '#64748B', fontWeight: 400 }}>({value.length} items)</span>
          </h4>
          
          {value.length === 0 ? (
            <div style={{ fontSize: '13px', color: '#94A3B8', fontStyle: 'italic' }}>No items added yet.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {value.map((item, index) => (
                <div key={index} style={{ padding: '12px', background: 'white', borderRadius: '6px', border: '1px solid #E2E8F0', display: 'grid', gap: '10px' }}>
                  <div style={{ fontSize: '11px', fontWeight: 700, color: '#94A3B8', textTransform: 'uppercase', marginBottom: '4px' }}>Item {index + 1}</div>
                  
                  {typeof item === 'object' && item !== null ? (
                    Object.keys(item).map(subKey => (
                      <div key={subKey}>
                        <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: '#475569', marginBottom: '4px', textTransform: 'capitalize' }}>
                          {subKey.replace(/_/g, ' ')}
                        </label>
                        <input 
                          type="text" 
                          value={item[subKey] || ''} 
                          onChange={(e) => {
                            const newList = [...value];
                            newList[index] = { ...newList[index], [subKey]: e.target.value };
                            handleChange(key, newList);
                          }}
                          style={{ width: '100%', padding: '8px 10px', border: '1px solid #CBD5E1', borderRadius: '4px', fontSize: '13px' }}
                        />
                      </div>
                    ))
                  ) : (
                    // Simple Array of Strings
                    <input 
                      type="text" 
                      value={item || ''} 
                      onChange={(e) => {
                        const newList = [...value];
                        newList[index] = e.target.value;
                        handleChange(key, newList);
                      }}
                      style={{ width: '100%', padding: '8px 10px', border: '1px solid #CBD5E1', borderRadius: '4px', fontSize: '13px' }}
                    />
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      );
    }

    // Boolean Checkbox
    if (typeof value === 'boolean') {
      return (
        <div key={key} style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '20px' }}>
          <input 
            type="checkbox" 
            checked={value}
            onChange={(e) => handleChange(key, e.target.checked)}
            style={{ width: '16px', height: '16px', accentColor: 'var(--color-orange)' }}
          />
          <label style={{ fontSize: '14px', fontWeight: 600, color: '#1E293B', textTransform: 'capitalize', cursor: 'pointer' }} onClick={() => handleChange(key, !value)}>
            {key.replace(/_/g, ' ')}
          </label>
        </div>
      );
    }

    // String/Number
    const isLongText = typeof value === 'string' && value.length > 50;
    
    return (
      <div key={key} style={{ marginBottom: '20px' }}>
        <label style={{ display: 'block', fontSize: '13px', fontWeight: 600, color: '#1E293B', marginBottom: '6px', textTransform: 'capitalize' }}>
          {key.replace(/_/g, ' ')}
        </label>
        {isLongText ? (
          <textarea 
            value={value || ''}
            onChange={(e) => handleChange(key, e.target.value)}
            style={{ 
              width: '100%', minHeight: '80px', padding: '10px 12px', 
              border: '1px solid #CBD5E1', borderRadius: '6px', 
              fontSize: '13px', fontFamily: 'inherit', resize: 'vertical' 
            }}
          />
        ) : (
          <input 
            type="text" 
            value={value || ''}
            onChange={(e) => handleChange(key, e.target.value)}
            style={{ 
              width: '100%', padding: '10px 12px', 
              border: '1px solid #CBD5E1', borderRadius: '6px', 
              fontSize: '13px' 
            }}
          />
        )}
      </div>
    );
  };

  return (
    <div style={{ padding: '24px', maxWidth: '800px', margin: '0 auto', background: '#FFFFFF' }}>
      <div style={{ marginBottom: '24px', paddingBottom: '16px', borderBottom: '1px solid #E2E8F0' }}>
        <h3 style={{ margin: '0 0 8px 0', fontSize: '16px', color: '#0F172A' }}>Smart Form Editor</h3>
        <p style={{ margin: 0, fontSize: '13px', color: '#64748B' }}>
          Edit the extracted document data without touching raw JSON. Changes made here will update the final payload.
        </p>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {Object.entries(data).map(([key, value]) => renderField(key, value))}
      </div>
    </div>
  );
}
