import React from 'react';
import { Routes, Route } from 'react-router-dom';
import { Sidebar, ToastContainer } from './components/Components';
import DashboardScreen from './screens/DashboardScreen';
import UploadScreen from './screens/UploadScreen';
import ImageUploadScreen from './screens/ImageUploadScreen';
import ValidationScreen from './screens/ValidationScreen';
import MappingScreen from './screens/MappingScreen';
import BulkScreen from './screens/BulkScreen';
import HistoryScreen from './screens/HistoryScreen';

export default function App() {
  return (
    <div className="app-layout">
      <Sidebar />
      <main className="main-content">
        <Routes>
          <Route path="/" element={<DashboardScreen />} />
          <Route path="/upload" element={<UploadScreen />} />
          <Route path="/upload/:uploadId/images" element={<ImageUploadScreen />} />
          <Route path="/upload/:uploadId/validation" element={<ValidationScreen />} />
          <Route path="/upload/:uploadId/mapping" element={<MappingScreen />} />
          <Route path="/bulk" element={<BulkScreen />} />
          <Route path="/history" element={<HistoryScreen />} />
        </Routes>
      </main>
      <ToastContainer />
    </div>
  );
}
