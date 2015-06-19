% Clean up sec.overview.alignments.rough_z.data
for s = 1:length(secs)
    % fprintf('%d\n', s);
    d = secs{s}.overview.alignments.rough_z.data;
    if isfield(d, 'manual_fixed_matching_pts')
        d.fixed_inliers = d.manual_fixed_matching_pts;
        d = rmfield(d, 'manual_fixed_matching_pts');
        d.manual = 'yes';
    end
    if isfield(d, 'manual_moving_matching_pts')
        d.moving_inliers = d.manual_moving_matching_pts;
        d = rmfield(d, 'manual_moving_matching_pts');
        d.manual = 'yes';
    end
    if ~isfield(d, 'manual')
        d.manual = 'no';
    end
    
    secs{s}.overview.alignments.rough_z.data = d;
end