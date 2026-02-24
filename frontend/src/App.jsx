import React from 'react';
import Chatbot from './components/Chatbot';
import './App.css';

function App() {
  return (
    <div className="App">
      <div className="main-content">
        <header className="app-header">
          <h1>VoxelBox Explore</h1>
          <p>Your neuroimaging analysis platform</p>
        </header>

        <section className="hero-section">
          <div className="hero-content">
            <h2>Advanced Brain Imaging Analysis</h2>
            <p>
              Process and analyze MRI, fMRI, and diffusion imaging data with 
              state-of-the-art tools and AI-powered insights.
            </p>
            <div className="cta-buttons">
              <button className="btn btn-primary">Get Started</button>
              <button className="btn btn-secondary">Learn More</button>
            </div>
          </div>
        </section>

        <section className="features-section">
          <div className="feature-grid">
            <div className="feature-card">
              <div className="feature-icon">🧠</div>
              <h3>Structural MRI</h3>
              <p>Advanced T1, T2, and FLAIR imaging analysis</p>
            </div>
            <div className="feature-card">
              <div className="feature-icon">📊</div>
              <h3>Functional MRI</h3>
              <p>Task-based and resting-state analysis</p>
            </div>
            <div className="feature-card">
              <div className="feature-icon">🔬</div>
              <h3>Diffusion MRI</h3>
              <p>Tractography and connectivity mapping</p>
            </div>
            <div className="feature-card">
              <div className="feature-icon">🤖</div>
              <h3>AI-Powered</h3>
              <p>Intelligent analysis and insights</p>
            </div>
          </div>
        </section>
      </div>

      <Chatbot />
    </div>
  );
}

export default App;