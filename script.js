const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

if (!reducedMotion && 'IntersectionObserver' in window) {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12 });
  document.querySelectorAll('.reveal').forEach((element) => observer.observe(element));
} else {
  document.querySelectorAll('.reveal').forEach((element) => element.classList.add('visible'));
}

const filters = document.querySelectorAll('.filters button');
const publications = document.querySelectorAll('.publication-list article');
filters.forEach((button) => {
  button.addEventListener('click', () => {
    filters.forEach((item) => item.classList.remove('active'));
    button.classList.add('active');
    publications.forEach((publication) => {
      const visible = button.dataset.filter === 'all' || publication.dataset.category === button.dataset.filter;
      publication.classList.toggle('hidden', !visible);
    });
  });
});

document.getElementById('year').textContent = new Date().getFullYear();
