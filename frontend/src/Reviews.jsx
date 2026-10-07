import { useEffect, useState } from "react";

import { getReviews, createReview, deleteReview } from "./api";

function Reviews() {
  const [reviews, setReviews] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [form, setForm] = useState({
    customer_name: "",
    menu_item: "",
    rating: 5,
    comment: "",
  });

  useEffect(() => {
    loadReviews();
  }, []);

  const loadReviews = async () => {
    try {
      setLoading(true);
      const data = await getReviews();
      setReviews(data);
    } catch (err) {
      console.error(err);
      setError("Failed to load reviews.");
    } finally {
      setLoading(false);
    }
  };

  const handleChange = (e) => {
    setForm({
      ...form,
      [e.target.name]: e.target.value,
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    try {
      await createReview({
        ...form,
        rating: Number(form.rating),
      });

      setForm({
        customer_name: "",
        menu_item: "",
        rating: 5,
        comment: "",
      });

      await loadReviews();
    } catch (err) {
      console.error(err);
      setError("Failed to save review.");
    }
  };

  const handleDelete = async (id) => {
    try {
      await deleteReview(id);
      await loadReviews();
    } catch (err) {
      console.error(err);
      setError("Failed to delete review.");
    }
  };

  const averageRating =
    reviews.length > 0
      ? (
          reviews.reduce((sum, item) =>sum + Number(item.rating || 0), 0) /
          reviews.length
        ).toFixed(1)
      : "0.0";

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h1>Customer Reviews</h1>
          <p>Track sentiment and guest feedback</p>
        </div>
      </div>

      {error && <div className="error-message">{error}</div>}

      <div className="stats-grid">
        <div className="stat-card">
          <h3>Total Reviews</h3>
          <strong>{reviews.length}</strong>
        </div>
        <div className="stat-card">
          <h3>Average Rating</h3>
          <strong>{averageRating}/5</strong>
        </div>
      </div>

      <div className="form-card">
        <h2>Add Review</h2>
        <form onSubmit={handleSubmit} className="form-grid">
          <input
            type="text"
            name="customer_name"
            value={form.customer_name}
            onChange={handleChange}
            placeholder="Customer name"
            required
          />
          <input
            type="text"
            name="menu_item"
            value={form.menu_item}
            onChange={handleChange}
            placeholder="Menu item"
          />
          <select name="rating"value={form.rating} onChange={handleChange}>
            <option value={5}>5 - Excellent</option>
            <option value={4}>4 - Good</option>
            <option value={3}>3 - Average</option>
            <option value={2}>2 - Poor</option>
            <option value={1}>1 - Very Poor</option>
          </select>
          <textarea
            name="comment"
            value={form.comment}
            onChange={handleChange}
            placeholder="Write feedback"
            rows={4}
            required
          />
          <div className="form-actions">
            <button type="submit"className="primary-btn">
              Submit Review
            </button>
          </div>
        </form>
      </div>

      <div className="table-card">
        <h2>Recent Feedback</h2>
        {loading ? (
          <p>Loading reviews...</p>
        ) : reviews.length === 0 ? (
          <p>No reviews available.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Customer</th>
                <th>Menu</th>
                <th>Rating</th>
                <th>Sentiment</th>
                <th>Comment</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {reviews.map((review) => (
                <tr key={review.id}>
                  <td>{review.customer_name}</td>
                  <td>{review.menu_item || "-"}</td>
                  <td>{review.rating || 0}/5</td>
                  <td>
                    <span
                      className={`chip ${review.sentiment === "Positive" ? "success" : review.sentiment === "Negative" ? "danger" : "warning"}`}
                    >
                      {review.sentiment || "Neutral"}
                    </span>
                  </td>
                  <td>{review.comment}</td>
                  <td>
                    <button
                      type="button"
                      className="secondary-btn"
                      onClick={() =>handleDelete(review.id)}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export default Reviews;
